---
title: "Cross-Cloud A2A: Why Cloud Run Is the Best Attester and the Worst Ingress"
published: false
description: A Cloud Run coordinator federating to AWS and Azure with no stored secrets. Why the metadata server is the strongest attestation available on serverless, why a Google identity means nothing to AWS until you say so, and the one Cloud Run setting that would collapse cross-cloud agent auth from N squared to N.
tags: googlecloud, cloudrun, a2a, aiagents
---

This article looks at what a Google Cloud coordinator can and cannot do when it calls agents on AWS and Azure over A2A, with no long-lived credential anywhere in the mesh.

The code is here:

[github.com/xbill9/multicloud-a2a-identity](https://github.com/xbill9/multicloud-a2a-identity)

#### What is this project trying to Do?

Three research agents on three clouds answer the same brief, and a coordinator scores what comes back. Google runs an ADK agent on Cloud Run. AWS runs a Strands agent on Bedrock AgentCore. Azure runs an Agent Framework agent on Container Apps.

The benchmark articles in this series measured how fast that goes. This one is about the part that decides whether it ships at all.

#### The Protocol Was Never the Problem

A2A does what it says. Cards resolve, tasks come back, and client libraries in three languages talk to each other without special cases. Across the benchmark series the timings tracked the remote model and runtime, never anything in the wire format.

Auth is where it stops. Every cross-cloud call needs a credential the far side will accept, and the far side is a different vendor with a different notion of what acceptable means. A2A leaves this alone on purpose — the client reads the scheme off the Agent Card and gets the credential *out of band*.

Out of band is the entire integration.

#### Why the Coordinator Runs on Cloud Run

Because Cloud Run's metadata server will mint an OIDC token with an audience you choose, and that one capability is what makes every outbound leg keyless.

```
GET /computeMetadata/v1/instance/service-accounts/default/identity
      ?audience=<your audience>
      &format=full
      &licenses=FALSE
```

Three legs, all starting there:

| leg | mechanism |
|---|---|
| GCP → GCP | Google ID token, audience pinned to the service URL |
| GCP → AWS | token to STS `AssumeRoleWithWebIdentity`, then SigV4 |
| GCP → Azure | token to an Entra Federated Identity Credential |

`format=full` is mandatory. Without it Google trims the token and drops the `email` claim, and trust conditions written against it stop matching — with no error that says so.

#### The Metadata Server Is the Strongest Attester You Can Get Here

This is the part that surprised me, and it cuts against a lot of current advice.

The usual recommendation for agent identity is SPIFFE and SPIRE. SPIRE's trust model starts with a node it can attest: an agent runs on that node, attests it to the server, then attests each local workload and hands out SVIDs over a Unix socket.

Cloud Run does not give you a node. An instance is created for a burst of traffic and destroyed, the service scales to zero between runs, and the next request may be served by something that did not exist a second earlier. There is no host to run a daemon on and nothing stable to observe.

The SPIFFE project knows. There is an RFC for serverless support, [spiffe/spire#1843](https://github.com/spiffe/spire/issues/1843), proposing an agentless path where the function attests directly to the server. It was opened in September 2020 and is still a proposal. What it proposes to attest *with* is the interesting part — for Google Cloud Functions, the identity token from the Compute Metadata Server. The same call the coordinator already makes.

On a substrate with no fixed node, the platform is the only party that can attest anything. It is the only one that knows which image is running, in which revision, under which service account, at the instant the token is minted.

The IETF's [WIMSE working group](https://datatracker.ietf.org/doc/charter-ietf-wimse/00-00/) says the same thing in a standards-track draft. [Workload Identity Practices](https://datatracker.ietf.org/doc/draft-ietf-wimse-workload-identity-practices/) documents the Instance Metadata Endpoint as an established industry pattern, listed beside SPIFFE rather than as the thing SPIFFE replaces.

#### What a Google Identity Actually Means to AWS

Less than the diagrams imply, and this is the point everything else follows from.

When the coordinator presents a Google-signed token to STS, AWS does two things. It fetches Google's public keys from a well-known OIDC discovery endpoint and checks the signature. Then it applies the conditions **you** wrote into the role's trust policy.

```json
"Principal": { "Federated": "accounts.google.com" },
"Condition": { "StringEquals": {
    "accounts.google.com:oaud": "sts.amazonaws.com",
    "accounts.google.com:sub":  "<service account numeric ID>"
}}
```

That is the whole mechanism. AWS learns that a token was signed by whoever holds a key Google published, and that `sub` is some number. It has never heard of your service account, your project or your agent.

Authentication crosses the boundary. Authorization never does. Delete the condition and the same valid token authorizes nothing.

Two things about that policy cost real time to learn:

- **Do not create an IAM OIDC provider for `accounts.google.com`.** AWS federates with Google natively, and adding an explicit provider produces `InvalidIdentityToken`. For Entra you *must* create one. Opposite rules, same-looking task.
- **The condition keys do not mean what they are named.** `accounts.google.com:oaud` is the token's `aud`. `accounts.google.com:aud` is its `azp`, which is a number. An audience string in `:aud` can never match, and the denial does not say why.

Pin `:sub` to the service account's numeric ID, never its email. An email can be freed and re-bound to a different principal.

#### What It Means Inside Cloud Run

The same question turned inward is more uncomfortable.

That identity belongs to the *service account*, which is attached to the service. Not to a revision, not to an instance, not to a request. The token proves one thing: something running as this service account asked for it.

It does not distinguish one revision from the next, so a rollback or a bad image carries the identity you reviewed. It does not distinguish concurrent requests. And it does not distinguish callers at all.

Reviewing this project for these articles turned up its own coordinator open to the internet on a public invoker binding. While that was true, an anonymous request arrived and was served by a container holding federated credentials for three clouds. The identity behaved correctly throughout. It was never designed to answer the question that mattered.

Two operational notes from closing it:

- **Cloud Run returns 401 and 403 for different reasons.** 401 means no usable ID token — wrong audience, an OAuth access token, malformed. 403 means the token is fine and the identity lacks `roles/run.invoker`. Reading 401 as a denial conflates a client bug with an authorization result. `gcloud auth print-identity-token` for a user account carries the gcloud OAuth client as its audience, so Cloud Run rejects it 401.
- **IAM revocation takes about two minutes to propagate.** Anonymous requests kept succeeding for that long after `allUsers` was removed, with the policy already reading correctly. A control run immediately after a revocation reports the hole still open and sends you looking for a second cause that does not exist.

#### The One Thing Cloud Run Should Change

Here is the argument, and it is narrower than most of what gets written about agent identity.

Three clouds means six directed cross-cloud edges, and each is settled independently by what the caller can present and what the callee will accept. Four is twelve. The integration count grows as N².

The **mint** side has converged. All three clouds will now issue an OIDC JWT with a caller-chosen audience to a workload holding no secret — Google via the metadata server, Azure via Entra, and AWS most recently through [IAM outbound identity federation](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_providers_outbound.html), which gives an account its own OIDC issuer and a `GetWebIdentityToken` call.

The **accept** side has not.

| runtime | inbound auth | foreign issuer |
|---|---|---|
| Bedrock AgentCore | SigV4, or a custom JWT authorizer taking any OIDC issuer | yes |
| Azure Container Apps | Entra on the ingress | Entra only |
| Cloud Run | IAM invoker check against a Google-signed ID token | Google only |

AgentCore's [inbound JWT authorizer](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/inbound-jwt-authorizer.html) takes a discovery URL, a list of allowed audiences validated against `aud`, and a list of allowed clients validated against `client_id`. Any OIDC-compliant issuer. That is ordinary OIDC and needs no new specification.

Cloud Run's invoker check validates Google-signed ID tokens and nothing else.

If every cloud's ingress accepted an OIDC discovery URL, an audience and a subject condition, the matrix would collapse from N² to N. Each cloud publishes one issuer for its workloads — all three now do. Each cloud accepts any issuer, subject to conditions you write. Six edges become three mints and three accept-configurations, and a fourth cloud costs one of each instead of six new integrations.

That is a change to two products, not a change to the industry. Google Cloud has already built the harder half — Workload Identity Federation is the most permissive federation of the three, taking a JWT from any OIDC issuer with a discovery document *and* an AWS-shaped subject token it replays against STS to learn who signed it. The generosity is all on the way in to Google's APIs. It stops at the Cloud Run ingress.

#### Where That Leaves SPIFFE

Not here, for this shape of deployment.

Adopting SPIRE would mean running a server, publishing a JWKS on DNS you manage, and pointing the AWS and Entra trust policies at it. You would still configure all three federations — SPIRE changes which issuer they trust, not how many there are. Count the places afterwards and it is four, not one, because SPIRE registration entries are a registry that did not exist before.

And the credential you would be presenting is weaker than the one you started with. The server observes nothing; it takes a Google token and re-signs its claims under a new name. That is a signing hop, not attestation, plus a CA key that becomes the most valuable secret you own — in a mesh whose whole point is that it has none.

SPIRE is the right answer when you own the nodes. On GKE the k8s node attestor works, the Workload API is a local socket with no public endpoint in the credential path, and workload attestation can distinguish a pod and a container image, which is finer than a service account. The coarseness problem described earlier is a serverless problem, and SPIRE solves it where it can reach.

#### What I Would Build Instead

Keep the metadata mint for the credential, and enforce audience separation — one token per destination, never a platform-internal credential reused against an external STS. The WIMSE practices draft calls that out specifically, and this mesh passes only because the audiences were chosen deliberately.

Then carry the delegation context *beside* the credential rather than inside it. A Google ID token's claim set is fixed — issuer, issued-at, expiry, audience, subject, authorized party, email, verified flag, and a Compute Engine block under `format=full`. No parameter adds a claim, so a GCP-rooted caller cannot put anything of its own in the token it presents.

A2A added an extension mechanism in v1.0.1, and the Secure Passport extension defines a `CallerContext` attached as metadata beside the task. [OAuth Transaction Tokens](https://datatracker.ietf.org/doc/draft-ietf-oauth-transaction-tokens/08/) define what should go in it. Between the two you get the delegation chain the cloud minters will not carry, on every runtime, without touching the credential path.

And the cheapest thing on this list: put a requester field on the run record. Until a run carries who asked for it, the audit trail names the coordinator as the actor for everything.

#### Summary

Cloud Run is the best attester in this mesh and the most restrictive ingress. It mints a platform-attested, audience-scoped token that nothing you install could improve on, and it will only accept tokens Google signed.

Cross-cloud agent auth is quadratic because every far end decides locally what a foreign signature may do. Changing who signs does not change that arithmetic. Making one ingress setting accept a standard OIDC discovery URL would.
