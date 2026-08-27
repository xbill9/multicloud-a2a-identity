# Measuring Least Privilege Across a Cloud Boundary

**A three-cloud A2A agent mesh with no stored secrets, and what a session policy on `AssumeRoleWithWebIdentity` proves that the rest of the agent-identity conversation only asserts.**

> Builder Center draft. Source, controls and raw findings:
> [github.com/xbill9/multicloud-a2a-identity](https://github.com/xbill9/multicloud-a2a-identity)

## The setup

Three research agents on three clouds answer the same brief and a coordinator scores what comes back. A Strands agent runs on Bedrock AgentCore, an ADK agent on Cloud Run, an Agent Framework agent on Azure Container Apps. They talk A2A.

The coordinator runs on Cloud Run because it is a runtime that will mint an OIDC token with an audience of your choosing, which makes every outbound leg a candidate for keyless federation. For the AWS leg that means: mint a token with `sts.amazonaws.com` as the audience, present it to `AssumeRoleWithWebIdentity`, sign the A2A call with what comes back. No access key exists anywhere in the mesh.

Every leg has a positive control and a negative control — run it as deployed, then run it again with the credential removed and confirm it is refused. A leg that answers proves nothing until the same leg denied without its credential. Eight probes, all holding.

## What the token does, and what it does not

Worth settling before the mechanics, because it is the distinction the rest of this rests on.

**The OIDC token authenticates. It carries no permissions at all.** On this leg the shape makes it obvious: the Google-signed assertion goes to STS, and what comes back — temporary credentials — is what signs the call. The token never touches the AgentCore request.

What AWS learns from it is narrow. It fetches Google's keys, checks the signature, and applies the conditions you wrote. It has never heard of your service account. Authentication crosses the boundary; authorization never does, and the audience is a replay boundary rather than a permission — it stops a token minted for STS being replayed against Entra, and because the caller chooses it, an audience-only condition proves only that *some* Google identity minted a token naming your resource.

There are no OAuth scopes anywhere in this flow. Every permission is IAM's, applied after the token has finished its one job — which is exactly why least privilege here is a session-policy question and not a token question.

## Two things about the trust policy

Both cost real time, and neither is discoverable from the error.

**Do not create an IAM OIDC provider for `accounts.google.com`.** AWS federates with Google natively. Adding an explicit provider produces `InvalidIdentityToken`. For Microsoft Entra you must create one — opposite rules for two tasks that look identical on a diagram.

**The condition keys do not mean what they are named.** `accounts.google.com:oaud` is the token's `aud` claim. `accounts.google.com:aud` is its `azp`, which is a number. An audience string placed in `:aud` can never match, and the denial does not say why.

```json
"Principal": { "Federated": "accounts.google.com" },
"Condition": { "StringEquals": {
    "accounts.google.com:oaud": "sts.amazonaws.com",
    "accounts.google.com:sub":  "<service account numeric ID>"
}}
```

Pin `:sub` to the service account's numeric ID rather than its email. An email can be freed and re-bound to a different principal; the number cannot.

One more, on the role policy rather than the trust policy: discovery is a separate action from invocation.

```json
"Action": [
  "bedrock-agentcore:InvokeAgentRuntime",
  "bedrock-agentcore:GetAgentCard"
]
```

A policy granting only `InvokeAgentRuntime` denies the agent-card fetch however the resources are written, and the failure surfaces nowhere near auth.

## The measurement

Session policies are the part of this worth writing about, because they turn a slogan into a result.

`AssumeRoleWithWebIdentity` accepts an optional inline `Policy` of up to 2,048 characters. The resulting session's permissions are the **intersection** of the role's identity-based policy and that session policy. There is no way to write one that grants something the role lacks.

That asymmetry is the whole value. The role is provisioned once by a deploy script and outlives every run. The session policy is chosen per process and costs nothing to make smaller.

The mesh's role is already scoped to two actions on one runtime ARN, so the question is whether a session can narrow below that, and whether the two actions come apart. Measured on the deployed mesh:

| session policy allows | card fetch | invocation |
|---|---|---|
| `GetAgentCard` only | allowed | **refused** |
| `InvokeAgentRuntime` only | **refused** | not reached |
| unattenuated | allowed | allowed |

Neither action substitutes for the other, in either direction, under a session the role would otherwise have permitted.

**AWS names the session policy as the layer that refused.** The denial reads "because no session policy allows the `bedrock-agentcore:InvokeAgentRuntime` action", which is distinguishable in the error text from a role-policy denial reading "no identity-based policy allows". A provider error that tells you which of two layers said no is rarer than it should be.

**The invoke-only run is what makes the card-only run believable.** When discovery is the narrowed action the leg never reaches the invocation, so the card fetch in the first row genuinely succeeded rather than being skipped.

Container exit code 3 is this CLI's only code meaning *denied*, which is what makes the result readable at all. A harness that infers a verdict from a wrapper's exit code conflates a denial with a dead credential and a crashed container — this project has been caught doing exactly that, reporting six clean denials while nothing was tested.

## Why this matters beyond one leg

Most current writing on agent identity asks for three things: no stored secrets, a preserved delegation chain, and permissions that shrink at every handoff. The third is the one a deployment can demonstrate rather than assert, and it is demonstrable because AWS built session policies years before anyone framed this as an agent problem.

The same is true of two fields already sitting in STS.

`SourceIdentity` is set once, cannot be changed, survives role chaining, and appears on every action taken with the role. Session tags do the same job for attributes. Between them they are the "who initiated this, and which agent acted" record the whole conversation is asking for.

Both are populated from claims inside the web identity token, not from request parameters, so the identity provider has to emit them. Since [IAM outbound identity federation](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_providers_outbound.html) shipped in November 2025, an AWS-rooted workload can: an account gets its own OIDC issuer, `GetWebIdentityToken` returns a signed JWT with the audience you ask for, and tags arrive as custom claims. [AWS's guidance on propagating user context](https://aws.amazon.com/blogs/security/propagate-user-authorization-context-in-ai-agents-with-amazon-bedrock-agentcore/) uses exactly that: an `https://aws.amazon.com/tags` claim becomes a session tag, and IAM conditions read it back through `aws:PrincipalTag/...`.

A caller rooted on a cloud whose metadata endpoint emits a fixed claim set cannot do any of that. Claim control is a property of the specific minter.

## The 64 characters nobody uses

`RoleSessionName` is required on every `AssumeRoleWithWebIdentity` call. Two to sixty-four characters, `[\w+=,.@-]`, chosen entirely by the caller, and it lands in the assumed-role ARN and in CloudTrail.

It is the only caller-supplied identity string in this mesh that reaches a cloud provider's audit log. This project sets it to a constant, which is defensible — a stale session name silently mislabels every call you make in someone else's audit log — but it means the one available field carries no per-run information.

A run correlator there would make a CloudTrail entry traceable to a specific run. The cost is one STS call per run instead of one per process, because the session name is fixed when the credential is minted and the credential is cached.

## What AgentCore gets right structurally

Three clouds means six directed cross-cloud edges, each settled by what the caller can present and what the callee will accept. Four clouds is twelve. The integration count grows as N².

All three clouds now mint an OIDC JWT with a caller-chosen audience. The difference is on the accept side, and AgentCore is the only one of the three whose agent ingress will validate a token from an issuer it does not own — a [custom JWT authorizer](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/inbound-jwt-authorizer.html) configured with a discovery URL, allowed audiences and allowed clients. Cloud Run's invoker check takes Google-signed ID tokens only. Container Apps ingress takes Entra.

The right way to read that is not that one cloud is ahead. **It is ordinary OIDC validation, done the ordinary way** — a resource server trusting a discovery document and checking two claims. The baseline is unremarkable; what is unusual is the deviation, two ingresses requiring an issuer they own.

If both did the ordinary thing the matrix would collapse from N² to N — three mints, three accept-configurations, and a fourth cloud costing one of each instead of six new integrations. That is a change to two products, not a change to the industry.

Nobody has this finished, including the cloud in the "yes" column: AgentCore Identity's outbound Microsoft credential provider is configured with a stored `clientSecret`. It is a different mechanism from outbound identity federation — OAuth access to Microsoft resources rather than workload identity — but the same vendor that ships a keyless way to authenticate to Entra configures that leg with a secret anyway.

AWS's Entra integration guide also notes support for v1.0 and v2.0 tokens "that do not have any custom claims", a constraint documented on that page rather than on the general authorizer — worth checking before routing custom claims through any issuer.

## And why an identity format will not fix it

The standing recommendation for this problem is SPIFFE and SPIRE, and it does not transfer to this shape of deployment. **SPIRE changes who signs your token; it does not change the fact that AWS, Azure and Google each decide, locally and separately, what that signature is allowed to do.**

SPIFFE gives every workload a passport your organisation issues. Calling AWS is not showing a passport, it is crossing a border, and the visa rules are written by the destination. Adopt SPIRE and AWS still needs a trust policy, Entra still needs a federated credential, Cloud Run still needs an invoker binding — you have upgraded the passport, and the visa count was never a property of the passport. On serverless there is also no node to attest, so the server ends up re-signing a metadata token's claims under a new name: a signing hop, plus a CA key, in a mesh whose whole point is that it holds no secrets. SPIRE is the right call when you own the nodes, which is a common case and not this one.

## Two operational findings

**Discovery and invocation are separately authorized on all three clouds**, which is why a credential belongs on the HTTP client rather than on one request. A card fetch that 403s while the call would have succeeded is the most confusing failure in this space.

**A control proves nothing until it has been re-run past the propagation window.** On the Google side of this mesh, IAM revocation took about two minutes to take effect — anonymous requests kept succeeding for that long after the binding was removed, with the policy already reading correctly. The same discipline applies anywhere: after changing an authorization policy, a probe that runs immediately is measuring the old state.

## Summary

A Strands agent on Bedrock AgentCore, reached over A2A from a coordinator on another cloud, with no access key in the mesh and eight controls behind the claim.

The measurable result is that permissions narrow across a federation boundary in both directions, and that AWS tells you which layer refused. That is the one thing in the current agent-identity conversation that a deployment can settle rather than argue, and the mechanism has been in STS for years.

The unused capacity is `SourceIdentity`, session tags and `RoleSessionName` — three places to record who initiated a call, all of them already there, none of them wired up by default.
