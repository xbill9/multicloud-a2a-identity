---
title: "Cross-Cloud A2A: AgentCore Is the Only Ingress That Takes a Foreign Token"
published: false
description: A three-cloud agent mesh with no stored secrets, and a measurement most agent-identity writing only asserts — permissions narrowing across a federation boundary, in both directions, with AWS naming which layer refused. Plus what the OIDC token in that exchange is actually for.
tags: aws, bedrock, a2a, aiagents
---

This article looks at the AWS leg of cross-cloud agent auth, measured on a deployed three-cloud A2A mesh with no long-lived credential anywhere in it.

The code is here:

[github.com/xbill9/multicloud-a2a-identity](https://github.com/xbill9/multicloud-a2a-identity)

#### What is this project trying to Do?

Three research agents on three clouds answer the same brief, and a coordinator scores what comes back. AWS runs a Strands agent on Bedrock AgentCore. Google runs an ADK agent on Cloud Run. Azure runs an Agent Framework agent on Container Apps.

The benchmark articles in this series measured how fast that goes. This one is about the auth, which is the part that decides whether it ships.

#### The Protocol Was Never the Problem

A2A does what it says. Cards resolve, tasks come back, and client libraries in three languages talk to each other without special cases.

Auth is where it stops. Every cross-cloud call needs a credential the far side will accept, and the far side is a different vendor with a different notion of what acceptable means. A2A leaves this alone on purpose — the client reads the scheme off the Agent Card and gets the credential *out of band*. Out of band is the entire integration.

#### The Short Answer

Split every cross-cloud call into two questions: can the caller mint a credential without holding a secret, and will the callee accept a credential signed by someone else.

The **mint** side has converged. All three clouds now issue an OIDC JWT with a caller-chosen audience to a workload holding no secret. The **accept** side has not:

| runtime | inbound auth | foreign issuer |
|---|---|---|
| Bedrock AgentCore | SigV4, or a custom JWT authorizer taking any OIDC issuer | yes |
| Azure Container Apps | Entra on the ingress | Entra only |
| Cloud Run | IAM invoker check against a Google-signed ID token | Google only |

Three clouds means six directed cross-cloud edges, four clouds is twelve, and every cell is the intersection of one cloud's mint format with another cloud's accept rules. Since the mint half is now uniform, every remaining difference is an accept-side difference. That is where the whole N² count comes from, and the rest of this article is what it looks like from the AWS side.

#### The AWS Leg, and Two Things That Cost Time

The coordinator runs on Cloud Run, mints an OIDC token from the metadata server with `sts.amazonaws.com` as the audience, presents it to `AssumeRoleWithWebIdentity`, and signs the A2A call with the returned credentials. No access key anywhere.

The trust policy:

```json
"Principal": { "Federated": "accounts.google.com" },
"Condition": { "StringEquals": {
    "accounts.google.com:oaud": "sts.amazonaws.com",
    "accounts.google.com:sub":  "<service account numeric ID>"
}}
```

- **Do not create an IAM OIDC provider for `accounts.google.com`.** AWS federates with Google natively and adding an explicit provider produces `InvalidIdentityToken`. For Entra you *must* create one.
- **The condition keys do not mean what they are named.** `accounts.google.com:oaud` is the token's `aud`. `accounts.google.com:aud` is its `azp`, a number. An audience string in `:aud` can never match.

And the role policy needs two actions, not one:

```json
"Action": [
  "bedrock-agentcore:InvokeAgentRuntime",
  "bedrock-agentcore:GetAgentCard"
]
```

Discovery is a separate action from invocation. A policy granting only `InvokeAgentRuntime` denies the agent-card fetch however the resources are written, which surfaces nowhere near auth. That is also why the credential belongs on the httpx *client* rather than on one request.

#### What That OIDC Token Is Actually For

Worth pausing on, because the AWS leg is the clearest illustration of a distinction that gets blurred everywhere else.

**The OIDC token authenticates. It carries no permissions at all.**

On this leg that is obvious from the shape: the Google-signed assertion goes to STS, and what comes back — temporary credentials — is what signs the actual call. The OIDC token never touches the AgentCore request. Its entire job is to authenticate one token exchange. Auth and access are two physically different objects.

On the other two legs the same token is handed straight to the ingress, so it authenticates *and* is the thing checked against an access rule, and it starts to look like the token grants access. It does not. Delete the invoker binding or the federated credential's role assignment and the identical, still-valid token returns 403.

What AWS learns from that assertion is also narrower than the diagrams suggest. It fetches Google's keys from a discovery endpoint, checks the signature, and applies the conditions **you** wrote. It has never heard of your service account or your project. Authentication crosses the boundary; authorization never does. The `sub` in that token means what your trust policy says it means and nothing else.

Which makes the audience a third thing that is neither identity nor permission. **`aud` is a replay boundary** — it stops a token minted for STS being replayed against Entra. And because the caller picks it, an audience-only condition proves only that *some* Google identity minted a token naming your resource. Pin the subject too, and pin it to the numeric ID: an email can be freed and re-bound.

One thing that surprises people: there are no OAuth scopes anywhere in this flow. No `scope` claim is honoured by anything. All the narrowing below happens in IAM, after the token has finished its one job.

#### The Measurement: Permissions Actually Narrow

"Permissions must shrink at each delegation" is easy to assert and rarely measured. It is measurable on AWS, because STS is the only one of the three exchanges that accepts a caller-supplied policy.

`AssumeRoleWithWebIdentity` takes an optional inline `Policy` of up to 2,048 characters. The resulting session gets the **intersection** of the role's policy and that one — there is no way to write a session policy that grants something the role lacks. The role is provisioned once and outlives every run; the session policy is chosen per process and costs nothing to make smaller.

The mesh's role is already scoped to two actions on one runtime ARN. So the test is whether a session can narrow further, and whether the two actions come apart.

| session policy allows | card fetch | invocation |
|---|---|---|
| `GetAgentCard` only | allowed | **refused** |
| `InvokeAgentRuntime` only | **refused** | not reached |
| unattenuated | allowed | allowed |

Neither action substitutes for the other in either direction. Two things in those refusals are worth more than the pass or fail:

**AWS names the session policy as the layer that refused.** The message reads "because no session policy allows the `bedrock-agentcore:InvokeAgentRuntime` action" — distinguishable in the error text from a role-policy denial, which reads "no identity-based policy allows". That is rare: a provider error that tells you which of two layers said no.

**The invoke-only run is what makes the card-only run believable.** When discovery is the narrowed action, the leg never reaches the invocation at all. That is how you know the card fetch in the first row genuinely succeeded rather than being skipped.

Of the three things agent-identity articles ask for, this is the one a deployment can demonstrate rather than assert. And it is demonstrable because AWS built session policies years ago. Nothing agent-specific was added.

#### The Ingress That Takes a Foreign Token

AgentCore's [inbound JWT authorizer](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/inbound-jwt-authorizer.html) takes a discovery URL matching `^.+/\.well-known/openid-configuration$`, a list of allowed audiences validated against `aud`, and a list of allowed clients validated against `client_id`. Any OIDC-compliant issuer.

It is worth being careful about how to read that, because the obvious reading is the wrong one. **This is not an AWS innovation — it is ordinary OIDC validation, done the ordinary way.** The baseline is a resource server that trusts a discovery document and checks two claims. What is unusual is the deviation: Cloud Run's invoker check validates Google-signed ID tokens and nothing else, and Container Apps ingress takes Entra.

So the sentence to take away is not that one cloud is ahead. It is that **two products require an issuer they own, and if they did the ordinary thing the matrix would collapse from N² to N.** Each cloud publishes one issuer for its workloads — all three already do. Each cloud accepts any issuer, subject to conditions you write. Six edges become three mints and three accept-configurations, and a fourth cloud costs one of each instead of six new integrations. That is a change to two products, not a change to the industry.

AWS's integration guide for Microsoft Entra notes support for Entra v1.0 and v2.0 tokens "that do not have any custom claims", a constraint documented on that page rather than on the general authorizer. Worth checking before you route custom claims through any issuer.

#### Outbound Identity Federation Closed the Last Gap

Until recently one cell in the matrix could not be done keyless, and this repository's code still says so in a comment. Entra's federated credential wants a JWT assertion from an issuer with OIDC discovery, and an ECS task role, a Lambda execution role or an AgentCore runtime role was not one. Outside EKS with IRSA, or Cognito, AWS had nothing of that shape to present — so an AWS-rooted coordinator calling Azure fell back to a stored client secret.

That changed in November 2025. [IAM outbound identity federation](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_providers_outbound.html) gives an account its own OIDC issuer URL, publishing `/.well-known/openid-configuration` and `/.well-known/jwks.json`. A workload obtains a signed JWT by calling [`GetWebIdentityToken`](https://docs.aws.amazon.com/STS/latest/APIReference/API_GetWebIdentityToken.html) with the audience it wants, and IAM policy controls which workloads may request tokens and with which audiences and lifetimes. AWS names the multi-cloud case explicitly.

So that comment describes a date, not a property of the two clouds — which is how a measured boundary turns into a permanent-sounding law if nobody re-tests it.

It also carries something the other two minters do not. Outbound tokens can carry tags that arrive as **custom claims**, which is how [AWS's own guidance on propagating user context](https://aws.amazon.com/blogs/security/propagate-user-authorization-context-in-ai-agents-with-amazon-bedrock-agentcore/) works — an `https://aws.amazon.com/tags` claim becomes a session tag, and IAM policy conditions read it back with `aws:PrincipalTag/...`.

Compare Google's metadata endpoint, which takes three query parameters and emits a fixed claim set with no way to add one. Claim control is a property of the specific minter, not of cloud metadata services in general.

#### The Field AWS Has and Nobody Uses

`SourceIdentity` is set once, cannot be changed, survives role chaining, and appears on every action taken with the role. Functionally it is the "who initiated this" field that every agent-identity article is asking for, shipped years before anyone framed it as an agent problem. Session tags do the same for attributes.

Both are filled from claims inside the web identity token, so the identity provider has to emit them. With outbound federation an AWS-rooted caller now can. A GCP-rooted one cannot.

And there is one more, easy to miss because it looks like a formality. `RoleSessionName` is required on every `AssumeRoleWithWebIdentity` call — two to sixty-four characters, `[\w+=,.@-]`, caller's choice — and it lands in the assumed-role ARN and in CloudTrail. It is the only caller-supplied identity string in this mesh that reaches a cloud provider's audit log, and it is currently a constant. A run correlator there makes a CloudTrail entry traceable to a specific run, for one extra STS call per run.

#### Where SPIFFE and SPIRE Fit

Not on this shape of deployment, and the reason compresses to a sentence: **SPIRE changes who signs your token, and it does not change the fact that AWS, Azure and Google each decide, locally and separately, what that signature is allowed to do.**

SPIFFE gives every workload a passport your organisation issues. Calling AWS is not showing a passport, it is crossing a border — and the visa rules are written by the destination. Adopt SPIRE and AWS still needs a trust policy, Entra still needs a federated credential, Cloud Run still needs an invoker binding. You have upgraded the passport; the visa count was never a property of the passport.

There is also nowhere to put the agent. SPIRE's trust model starts with a node it can attest, and AgentCore, Container Apps and Cloud Run do not give you one. The RFC for serverless support, [spiffe/spire#1843](https://github.com/spiffe/spire/issues/1843), was opened in September 2020 and is still a proposal — and what it proposes to attest *with* is a SigV4-signed `GetCallerIdentity` query the server replays, a primitive this framework already calls directly. Without a node the server observes nothing: it receives a token and re-signs its claims under a new name, so the SVID means whatever the original token meant. That is an identity weaker than the one it wrapped, plus a CA key to protect and a JWKS endpoint you host in front of all three legs — a mesh whose legs fail independently gains one shared dependency.

SPIRE is the right call when you own the nodes. On EKS the node attestor works, the Workload API is a local socket, and X.509-SVIDs give you workload mTLS that no cloud federation primitive provides.

#### One Thing the Product Does That the Docs Argue Against

AgentCore Identity's outbound Microsoft credential provider is configured with a stored `clientSecret`:

```json
{
  "credentialProviderVendor": "MicrosoftOAuth2",
  "oauth2ProviderConfigInput": {
    "microsoftOauth2ProviderConfig": {
      "clientId": "your-client-id",
      "clientSecret": "your-client-secret",
      "tenantId": "your-microsoft-entra-tenant"
    }
  }
}
```

That is a different mechanism from outbound identity federation — an OAuth credential provider for access to Microsoft resources, not workload identity — so the two are not in conflict. But the same vendor that ships a keyless way for a workload to authenticate to Entra configures that leg of its agent identity service with a client secret anyway. This mesh does it with a federated credential and none. No cloud has this finished.

#### Summary

Three agents deployed across three clouds, federating three ways, no stored secrets, eight controls behind it — each leg run as deployed and run again with its credential removed to confirm it is refused.

The OIDC token in the AWS exchange does exactly one job: it authenticates, and it carries a replay boundary in its audience. Every permission is IAM's, applied after the fact, in a language that does not cross the boundary. That is why no identity format fixes this, SPIFFE included.

AgentCore validates a token from an issuer it does not own, which is ordinary OIDC rather than an achievement — the gap is the two ingresses that require their own issuer, and closing it is a product change rather than an industry-wide adoption of anything.

And the one claim in this discourse that a deployment can prove rather than assert happens to be testable on AWS: permissions narrow across a federation boundary, in both directions, with the provider naming which layer refused.
