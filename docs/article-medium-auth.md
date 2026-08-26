# Cross-Cloud Agent Auth is an N² Problem

### Three clouds means six directed edges and each one is a separate integration — but the asymmetry that causes it sits in a narrower place than the usual advice suggests, and one vendor has already fixed both halves of it

A2A is not what limits a multi-cloud agent mesh. Auth is. This article is about what a deployed three-cloud mesh shows when you measure that rather than draw it.

The code, the controls and the raw findings are here:

[github.com/xbill9/multicloud-a2a-identity](https://github.com/xbill9/multicloud-a2a-identity)

#### The Protocol is the Easy Part

A2A does what it says. Cards resolve, tasks come back, and client libraries in three languages talk to each other without special cases. Across the benchmark series that preceded this one, the timings tracked the remote model and runtime, never anything in the wire format. There is no protocol work left to do to run agents on three clouds.

Auth is where it stops. Every cross-cloud call needs a credential the far side will accept, and the far side is a different vendor with a different notion of what acceptable means. A2A leaves this alone on purpose: the client reads the scheme off the agent card and gets the credential **out of band**.

Out of band is the entire integration.

Ask what to do about it and you get pointed at SPIFFE and SPIRE. This article argues three things against that, from a mesh that is deployed and controlled rather than drawn. Cross-cloud agent auth is a quadratic integration problem, not an identity-format problem. The asymmetry that makes it quadratic is on the *accept* side, not the mint side. And the fix is a change to two products rather than an industry-wide adoption of anything.

#### What This Mesh Measured

Three research agents on GCP, AWS and Azure, coordinated from Cloud Run. Every outbound leg starts at the same place — the metadata server issues a short-lived OIDC token with whatever audience you ask for — then diverges by cloud. Google ID token to Cloud Run, token to STS `AssumeRoleWithWebIdentity` then SigV4 for AWS, token to an Entra Federated Identity Credential for Azure.

No stored secrets on any of them. Each leg has a positive control and a negative control — run it as deployed, then run it again with the credential removed and confirm it is refused. A leg that answers is worth nothing until the same leg denied without its credential. There is also a wrong-audience probe on the GCP leg, which separates *this identity is checked* from *some token is checked*. Eight probes, all holding.

#### Permissions Narrow Across a Federation Boundary

An inline session policy on `AssumeRoleWithWebIdentity` intersects with the role's own policy and can never widen it, so a session can be scoped below what the role permits, per call rather than per deployment.

![Session policy varied on the AWS leg, measured on the deployed mesh on 25 August 2026. With the session policy allowing GetAgentCard only, the card fetch is allowed and the invocation is refused. With the session policy allowing InvokeAgentRuntime only, the card fetch is refused and the invocation is never reached. Unattenuated, both are allowed. Both refusals name the session policy as the layer that refused.](img/medium/auth-02-attenuation.png)

Neither action substitutes for the other in either direction. Both refusals name the session policy as the layer that refused, which distinguishes an attenuation refusal from a role refusal without guessing. The invoke-only run is what proves discovery genuinely succeeded in the card-only run rather than being skipped.

Of the three things agent-identity articles ask for, this is the one a deployment can demonstrate rather than assert.

#### Two Operational Findings Worth Having

Cloud Run returns **401** when there is no usable ID token — wrong audience, an OAuth access token, malformed — and **403** when the token is fine and the identity lacks `roles/run.invoker`. Reading 401 as a denial conflates a client bug with an authorization result.

And IAM revocation takes about two minutes to propagate. Anonymous requests kept succeeding for that long after a binding was removed, with the policy already reading correctly. A control run immediately after a revocation reports the hole still open and sends someone looking for a second cause that does not exist.

Reviewing this project for these articles turned up its own coordinator open to the internet on a public invoker binding, serving a container that holds federated credentials for three clouds. The controls found it. They found it four days later, which is an argument for running them on a schedule rather than before a write-up.

#### Multicloud Means Two Different Things

The word does double duty, and the two meanings have nothing in common except the adjective.

**Meaning A, which is what SPIRE is for:** my workloads, spread across clouds. You own the compute. Clusters on EKS, GKE and AKS, one organisation, one administrative boundary drawn around all of it. You control the nodes, you choose the identity format, both ends of every call are yours, and one trust domain is a coherent idea.

**Meaning B, which is what an agent mesh is:** my agent, calling other vendors' services. You own one end. The others are managed runtimes — Bedrock AgentCore, Azure Container Apps, Cloud Run — each with its own idea of a valid caller. You control no nodes, each far end dictates the format, and there are three trust domains of which you administer one.

SPIFFE was built for the first. It gives identity to workloads inside a boundary you control and it is good at that. An agent mesh is the second, where the hard part is that the far end is not yours and never will be.

"SPIFFE is good for multicloud" is true of meaning A and gets repeated as though it were true of meaning B. The difficulty in meaning B is not that your workloads lack an identity. It is that three vendors each have their own rules about which identities they accept, and no identity format you adopt changes that.

#### What a Cloud Identity Means Somewhere Else

Less than the diagrams imply, and this is the point everything else follows from.

When the coordinator presents a Google-signed token to STS, AWS does two things. It fetches Google's public keys from a well-known OIDC discovery endpoint and checks the signature. Then it applies the conditions **you** wrote into the role's trust policy — this audience, this subject.

That is the whole mechanism. AWS learns that a token was signed by whoever holds a key Google published, and that the token says `sub` is some number. It has never heard of your service account, your project or your agent.

Authentication crosses the boundary. Authorization never does. The number in that token means what your trust policy says it means and nothing else. Delete the condition and the same valid token authorizes nothing.

There is no such thing as a cross-cloud identity. There is a locally defined mapping, at each far end, from a foreign signature to a local principal. Three far ends, three mappings — and that count is a property of the boundaries, not of the issuer. Change who signs and you have changed the signature, not the arithmetic.

#### And What It Means on Cloud Run

The same question turned inward is more uncomfortable.

That identity belongs to the *service account*, which is attached to the service. Not to a revision, not to an instance, not to a request. The token proves one thing: something running as this service account asked for it.

It does not distinguish one revision from the next, so a rollback or a bad image carries the identity you reviewed. It does not distinguish concurrent requests. And it does not distinguish callers at all — which is why an anonymous request, during the window described above, was served by a container holding three clouds' credentials.

There is also no fixed node underneath it. A Cloud Run instance is created for a burst of traffic and destroyed, the service scales to zero between runs, and the next request may be served by something that did not exist a second earlier.

The substrate pulls two ways at once. The identity is too coarse — one service account across every revision and request. The compute is too fluid — no durable node to attest. SPIRE needs a stable node it can vouch for and an agent living on it long enough to vouch for the workloads above. Serverless offers neither half.

On a substrate with no fixed node, the platform is the only party that can attest anything. It is the only one that knows which image is running, in which revision, under which service account, at the instant the token is minted.

#### Six Edges

Three clouds means six directed cross-cloud edges, and each is settled independently by what the caller can present and what the callee will accept. This mesh runs three of them — it is rooted on GCP, so the GCP-origin rows are what is deployed. The rest come from the reverse-root experiment in the repository and from the vendors' own documentation.

![Six directed edges between three clouds, sourced 25 August 2026, all six keyless. GCP to AWS and GCP to Azure are deployed and controlled, via a metadata JWT to STS AssumeRoleWithWebIdentity and to an Entra federated credential. AWS to GCP is code written but not deployed. AWS to Azure and Azure to GCP are vendor-documented but not built. Azure to AWS follows from both vendors' docs rather than a measurement, the weakest cell.](img/medium/auth-01-six-edges.png)

Read the evidence column as four distinct claims. **Deployed and controlled** means it ran against the live cloud and has a negative control behind it. **Code written** means the implementation exists in this repository and has not been run against the provider. **Vendor-documented** means the provider documents the mechanism and this project has not built it. The last row combines two vendors' documented capabilities and is the weakest cell in the table.

Six edges, six configurations, no two alike. That is the quadratic problem in one image, and it is worth being precise about why it is quadratic: each cell is the intersection of one cloud's mint format and another cloud's accept rules, and neither is standardised.

#### The Edge That Closed While This Was Being Written

Until recently, AWS to Azure was the cell that could not be done keyless, and this repository's code says so in a comment. Entra's federated credential wants a JWT assertion from an issuer with OIDC discovery, and an ECS task role, a Lambda execution role or an AgentCore runtime role was not one. Outside EKS with IRSA, or Cognito, AWS had nothing of that shape to present, so the leg fell back to a stored client secret.

That changed in November 2025. AWS IAM outbound identity federation gives an account its own OIDC issuer URL, publishing the standard OIDC discovery endpoints, and workloads obtain a signed JWT by calling `GetWebIdentityToken` with the audience they want. AWS names the multi-cloud case explicitly, and IAM policy controls which workloads may request tokens and with which audiences and lifetimes.

So the mint side has converged and the repository's comment is now dated. All three clouds can issue an OIDC JWT with a caller-chosen audience to a workload holding no secret. That is worth stating plainly because it removes what looked like a structural asymmetry between the vendors.

It also removes a claim these articles lean on. AWS's outbound tokens can carry tags that arrive as custom claims, which is how AWS's own guidance propagates user context — a tags claim in the token becomes a session tag, and IAM policy conditions read it back. Claim control is therefore a property of the specific minter, not of cloud metadata services in general. Google's metadata identity endpoint takes three query parameters — audience, format and licenses — and emits a fixed claim set. No parameter adds a claim, so a GCP-rooted caller cannot put anything of its own in the token it presents. An AWS-rooted caller can attach tags that arrive as custom claims, which is enough for attribute-based decisions at the far end and short of a nested delegation chain.

#### The Accept Side is Where the Problem Lives

If all three clouds can mint an OIDC JWT, the quadratic count has to be coming from somewhere else. It is coming from the ingress — whether a runtime will validate a token from an issuer it does not own.

![Will the ingress accept a foreign issuer? Bedrock AgentCore accepts SigV4 or a custom JWT authorizer taking any OIDC issuer, so yes. Azure Container Apps uses Entra on the ingress, so Entra only. Cloud Run uses an IAM invoker check against a Google-signed ID token, so Google only. Every cloud can mint an OIDC JWT for a workload holding no secret, and one of the three will validate a token from an issuer it does not own.](img/medium/auth-03-ingress.png)

AgentCore's inbound JWT authorizer takes a discovery URL, a list of allowed audiences validated against `aud`, and a list of allowed clients validated against `client_id`. Any OIDC-compliant issuer. That is ordinary OIDC and it needs no new specification.

One scoping note, because it is easy to over-read. AWS's integration guide for Microsoft Entra states that it supports Entra v1.0 and v2.0 access and ID tokens "that do not have any custom claims." That constraint is documented on the Entra-specific page; the general authorizer documentation describes discovery URL, audiences and clients without a corresponding restriction. Treat the no-custom-claims line as applying to the Entra integration as documented, and test before relying on custom claims through any issuer.

**If every cloud's ingress accepted an OIDC discovery URL, an audience and a subject condition, the matrix would collapse from N² to N.** Each cloud publishes one issuer for its workloads — all three now do. Each cloud accepts any issuer, subject to conditions you write — one of three does. Six edges become three mints and three accept-configurations, and adding a fourth cloud costs one of each instead of six new integrations.

That is a change to two products, not a change to the industry. And it explains why the SPIRE proposal feels like it should work: one issuer everyone trusts achieves the same collapse, but buys it by adding a party rather than by removing a restriction. The restriction is the cheaper thing to remove, and AWS has already removed it on both sides — it issues OIDC to its workloads and accepts OIDC from anyone.

#### There is More Prior Art Than It Looks Like

Search for agent identity and you get opinion pieces. The engineering is there, filed in three places that do not cite each other.

**The protocol work split the problem in two.** The IETF WIMSE working group is chartered for least-privilege access control for workloads across multiple platforms, with an architecture draft, a Workload Identifier, Workload Credentials, and a Workload Proof Token binding a workload's authentication to a specific HTTP request. Its Workload Identity Practices draft — Schwenkschuster and Rosomakho, draft 06, August 2026 — surveys how workloads get credentials today and documents the Instance Metadata Endpoint as an established industry pattern, listed beside SPIFFE rather than as the thing SPIFFE replaces. It also carries a requirement worth auditing against: a credential for internal platform access should not be reused to federate to an external STS, because that conflates trust and audience boundaries. This mesh mints a separate token per destination, so it passes, because the audiences were picked deliberately.

OAuth Transaction Tokens, draft 08, March 2026, cover the other half: short-lived signed JWTs carrying user identity, workload identity and authorization context along a call chain, issued by a service implementing a profile of the OAuth 2.0 Token Exchange endpoint, and cryptographically protected so downstream workloads cannot alter what they were handed. There is an agent extension using `sub` for the principal and `act` for the agent acting; its draft 06 expired in April 2026 and was replaced by an individual submission.

This is the microservices industry having already learned the lesson. Passing the caller's access token down the chain does not work. The fix was a separate token for the chain, not a better credential for the workload.

**The governance frameworks say what and not how.** The Cloud Security Alliance has an Agentic AI Identity and Access Management paper and an Agent Identity Governance Framework. The OWASP Top 10 for Agentic Applications 2026 treats agents as operational actors with delegated authority, and two of its categories are Identity and Privilege Abuse, and Insecure Inter-Agent Communication. NIST issued a Request for Information on AI Agent Security in early 2026 and a concept paper on AI Agent Identity and Authorization. None of them tells you which token goes in which header.

**And the products are where cross-cloud actually shows up.**

![Vendor agent identity in 2026. Bedrock AgentCore Identity is generally available, an inbound authorizer plus an outbound token vault. Microsoft Entra Agent ID is in preview, treating agents as directory objects under Conditional Access. Vertex AI Agent Engine identities have shipped, inside Google's agent runtime. Three registries, no interoperable protocol between them, and cross-cloud works where one vendor has chosen to support another.](img/medium/auth-05-vendor-products.png)

They address cross-cloud bilaterally. Microsoft documents securing a Bedrock agent with Entra Agent ID and surfacing agents from Bedrock, Vertex and Databricks in one registry. AWS documents Entra as an inbound identity provider for AgentCore Runtime and Gateway.

Every one of those is a vendor integration, not a federation. Each cloud keeps its own registry and its own mapping, and cross-cloud works because one vendor decided to support another. Nobody fills a quadratic matrix by negotiation, and the cells that stay empty are the ones where two vendors have no commercial reason to care about each other's workloads.

One detail from the AgentCore documentation is worth noting against the discourse these products are sold into: the outbound Microsoft credential provider is configured with a stored client secret. That is a separate mechanism from the outbound identity federation described above — a credential provider for OAuth access to Microsoft resources rather than workload identity — so the two are not in conflict. The observation is about the product: AWS ships a keyless way for a workload to authenticate to Entra, and its agent identity service configures that leg with a client secret anyway.

#### Where SPIRE Fits

Put SPIRE against the split the standards made and it is a credential system — a good one, for meaning A. It says nothing about a call chain, and the delegation problem these articles open with sits entirely in the second half.

![Adopting SPIRE on a serverless agent mesh. The token minter goes from a managed metadata server to a SPIRE Server you run. Attestation on serverless goes from built into the runtime to an open RFC since 2020. Public endpoints to operate goes from none to OIDC discovery on your own DNS. Federations still required stays at three. Places identity is pinned goes from three to one. Control over token claims goes from none to yours.](img/medium/auth-04-spire-cost.png)

Every agent in this mesh consumes external OIDC and carries on doing so. AWS still needs a trust policy, Entra still needs a federated credential, Cloud Run still needs an invoker binding. SPIRE changes which issuer those three trust; it does not reduce their number, and configuring them is the work. Count the places afterwards and it is four, not one, because SPIRE registration entries are a registry that did not exist before.

It also changes the shape of the configuration. Google is a native AWS identity provider, so you must not create an IAM OIDC provider for it — doing so breaks federation. SPIRE is not native, so the IAM OIDC provider becomes required and the conditions key on a discovery domain you host. Opposite rules for two tasks that look identical on a diagram.

And there is nowhere to put the agent. There is an RFC for serverless support, spiffe/spire issue 1843, proposing an agentless path where the function attests directly to the server. Opened September 2020, still a proposal. What it proposes to attest *with* is the part to read: for Google Cloud Functions, the identity token from the Compute Metadata Server; for AWS Lambda, a SigV4-signed `GetCallerIdentity` query the server replays. Those are the two primitives this framework already calls directly.

#### But You Could Make It Work

You could, and the design deserves writing out, because it is the obvious response to everything above.

Nobody says the SPIRE agent has to run on the serverless runtime. Only the caller needs an identity and there is one caller. Run the server on a VM or a small GKE cluster. Have the coordinator present its Cloud Run metadata token to the server and get back a JWT-SVID carrying whatever claims you want. Publish the JWKS through the OIDC Discovery Provider, point the AWS and Entra trust policies at it, and you have one SPIFFE ID and full control of the claim set.

That works on a whiteboard. Four things it costs.

**The SVID is asserted, not attested.** SPIFFE's value is attestation — an identity bound to something observed about the workload. In this design the server observes nothing. It receives a Google token and re-signs its claims under a new name. The SPIFFE ID then means exactly what the Google token meant, because that is the only evidence in the chain. You have added a signing hop and a private key to look after, so the identity is weaker than the one it wrapped.

**It creates a new secret zero, and it is the best one in the building.** The CA signing key becomes the most valuable secret you own. Take it and you mint identities that AWS and Entra accept for your roles, and the metadata server they think they are trusting is never consulted. The goal was no long-lived secrets anywhere in the mesh, and today there are none.

**The GCP leg cannot use it.** Cloud Run's invoker check validates Google-signed ID tokens. It does not take an arbitrary external issuer, so a JWT-SVID is not a credential that leg can use. Skip that leg and you run SPIFFE for two clouds while the third keeps Google tokens; or exchange the SVID back into a Google credential through Workload Identity Federation, which means minting a Google token, converting it to an SVID, then converting it back.

**And SPIFFE Federation is not the escape hatch.** The specification defines an exchange of trust bundles between trust domains, each publishing an HTTPS bundle endpoint the other polls. That needs the far side to be a SPIFFE trust domain publishing a SPIFFE bundle endpoint. AWS is not one. Neither is Azure, nor Google.

The one I would refuse on even if the others were solved: AWS and Entra validate a JWT-SVID by fetching your JWKS over the public internet, so every cross-cloud call depends on a discovery endpoint you run, on DNS you manage, behind a certificate you renew. Today the three legs fail independently. Add the discovery provider and you have three independent dependencies plus one shared one in front of them. Multicloud is supposed to buy independence. This spends it.

#### Where SPIRE is the Right Call

Meaning A, and the case is stronger than the space it gets here.

On Kubernetes, nearly every objection above disappears. Nodes exist, so the k8s node attestor works and the identity is genuinely attested rather than re-signed. The Workload API is a Unix socket next to the workload, so there is no public endpoint in the credential path and no shared failure mode. Workload attestation can distinguish a pod, a service account and a container image, which is finer than a cloud service account — the coarseness problem described earlier is a serverless problem, and SPIRE solves it where it can reach.

At scale the pinning arithmetic reverses. Three identities across three clouds is a script. Fifty microservices with per-service identities is not.

And X.509-SVIDs give you mutual TLS between workloads, which none of the three clouds' federation primitives provide.

The argument here is narrow and worth stating as such: SPIRE is the wrong tool for a serverless agent mesh calling managed runtimes on three vendors. It is a good tool for the case it was designed for, and that case is common.

#### What to Build Instead

Follow the split the standards made. A credential identifies the workload. A separate token carries the chain.

**Layer one, who is calling.** Keep the metadata mint. It is attested by the only party positioned to attest anything on serverless, costs nothing to run, and WIMSE documents it as an established pattern rather than a shortcut. Enforce audience separation: one token per destination, never a platform-internal credential reused against an external STS.

**Layer two, on whose behalf and through whom.** A Transaction Token Service sits at the edge, takes the incoming request and whatever authenticated the requester, and issues a short-lived signed JWT with `sub` for the principal and `act` for the agent acting. Each agent presents it and requests a new one to call the next hop, so the chain accumulates instead of being asserted. The token is immutable in transit, and it is separate from the credential, so it is unaffected by three clouds each dictating their own credential format. Unlike a SPIRE server it is not in the credential path: if it is down you stop starting new work, and no cloud is fetching keys from you to validate a login.

**Layer three, carried by the protocol.** A2A added an extension mechanism in v1.0.1, and the Secure Passport extension defines a `CallerContext` attached beside the task with a client identifier, state and a signature. Use the extension as the envelope and a transaction token as the payload and the two gaps cancel. Declare it on the agent card as well — A2A carries `securitySchemes` in OpenAPI 3 shape plus a `security` block mapping scopes to individual skills, and most deployments declare far less than the spec allows.

**Layer four, narrowing per hop.** The measurement near the top of this article is that layer working.

And the two-afternoon version, if none of that is happening this quarter: put a requester field on the run record, because until a run carries who asked for it the audit trail names the coordinator as the actor for everything. Then use `RoleSessionName` — required on every `AssumeRoleWithWebIdentity` call, caller's choice, two to sixty-four characters, and it lands in CloudTrail. It is the only caller-supplied identity string in this mesh that reaches a cloud provider's audit log, and it is currently a constant.

#### Summary

Cross-cloud agent auth is quadratic. Three clouds is six directed edges, four is twelve, and each cell is the intersection of one cloud's mint format with another cloud's accept rules.

The mint side has converged: all three clouds now issue an OIDC JWT with a caller-chosen audience to a workload holding no secret, AWS most recently. The accept side has not — AgentCore validates a token from any OIDC issuer, and Cloud Run and Container Apps take only their own. That is where the quadratic count comes from, and it is a change to two products rather than an industry-wide adoption of anything.

SPIFFE and SPIRE do not fix it, because a cloud identity has no meaning outside its cloud. Each far end decides locally what a foreign signature may do, so the mapping exists once per boundary no matter who signs. Change the issuer and you have changed the signature, not the arithmetic — while adding a server, a public endpoint and a CA key to a mesh that had no secrets.

What is missing is narrower than the articles suggest, and the standards split it correctly: a credential identifies the workload, and a separate token carries the call chain.
