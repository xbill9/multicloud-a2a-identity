# Cross-Cloud Agent Auth is an N² Problem

### Three clouds means six directed edges and every one is a separate integration. The asymmetry that causes it is narrower than the usual advice suggests — it sits on the accept side, in two products, and no identity format you adopt will move it.

A2A is not what limits a multi-cloud agent mesh. Auth is. This article is about what a deployed three-cloud mesh shows when you measure that rather than draw it.

The code, the controls and the raw findings are here:

[github.com/xbill9/multicloud-a2a-identity](https://github.com/xbill9/multicloud-a2a-identity)

#### The Protocol is the Easy Part

A2A does what it says. Cards resolve, tasks come back, and client libraries in three languages talk to each other without special cases. Across the benchmark series that preceded this one, the timings tracked the remote model and runtime, never anything in the wire format. There is no protocol work left to do to run agents on three clouds.

Auth is where it stops. Every cross-cloud call needs a credential the far side will accept, and the far side is a different vendor with a different notion of what acceptable means. A2A leaves this alone on purpose: the client reads the scheme off the agent card and gets the credential **out of band**.

Out of band is the entire integration.

#### The Short Answer

Split every cross-cloud call into two questions. Can the caller mint a credential without holding a secret? Will the callee accept a credential signed by someone else?

![Will the ingress accept a foreign issuer? Bedrock AgentCore accepts SigV4 or a custom JWT authorizer taking any OIDC issuer, so yes. Azure Container Apps uses Entra on the ingress, so Entra only. Cloud Run uses an IAM invoker check against a Google-signed ID token, so Google only. Every cloud can mint an OIDC JWT for a workload holding no secret, and one of the three will validate a token from an issuer it does not own.](img/medium/auth-03-ingress.png)

The mint side has converged. All three clouds now issue a short-lived OIDC JWT, with an audience the caller chooses, to a workload holding no secret. Google's metadata server has done it for years, Entra federated credentials do it, and AWS closed its half in November 2025 with IAM outbound identity federation.

The accept side has not. One ingress of the three will validate a token from an issuer it does not own.

That is where the quadratic count comes from, and it is worth being precise about the shape. Each cell in the matrix is the intersection of one cloud's mint format with another cloud's accept rules. The mint half is now uniform, so every remaining difference is an accept-side difference. **If all three ingresses took a discovery URL, an audience and a subject condition, the matrix would collapse from N² to N** — six edges become three mints and three accept-configurations, and a fourth cloud costs one of each instead of six new integrations.

Nothing in that requires a new specification. AgentCore's inbound authorizer takes a discovery URL, a list of allowed audiences checked against `aud`, and a list of allowed clients checked against `client_id`. That is ordinary OIDC, done the ordinary way. It is not an innovation and reading it as one gets the situation backwards: **plain OIDC validation is the baseline, and two products deviate from it by requiring an issuer they own.** The fix is those two products moving to the baseline.

#### What the OIDC Token Is Actually For

This is the question most readers arrive with, and the answer is narrower than the diagrams suggest.

**The OIDC token authenticates. It carries no permissions at all.** Every permission in this mesh is expressed in a cloud-native policy language at the far end — three different ones — and none of it travels in the token.

The reason this feels murky is that the token plays two structurally different roles depending on the leg.

**Exchanged.** On the AWS leg the OIDC assertion goes to STS `AssumeRoleWithWebIdentity` and comes back as temporary credentials, and those credentials sign the actual call with SigV4. The OIDC token never touches the API request. Its entire job is to authenticate one token exchange. Auth and access are two physically different objects here, so nobody confuses them.

**Presented.** On the Cloud Run and Container Apps legs, and on an AgentCore runtime configured with a JWT authorizer, one token is handed to the ingress and that is the whole flow. It authenticates *and* it is the thing checked against an access rule. Same object, two jobs — which is exactly why it looks like the token grants access. It does not. The grant is the invoker binding, the federated credential's role assignment, the authorizer's audience list. Delete that local rule and the identical, still-valid token returns 403.

Audience is the third thing that gets folded into the other two, and it is neither. **Audience is a replay boundary.** It says this token was intended for one destination, which stops a token minted for AWS being replayed against Azure. That is confused-deputy protection — blast radius, not permission. And because the audience is chosen by the caller, an audience-only trust condition proves only that *some* identity in that IdP minted a token naming your resource. Anyone in that directory can do that. You need both halves: subject for who, audience for where, with the subject pinned to an immutable numeric ID rather than an email, which can be freed and re-bound.

One more thing worth stating plainly, because it surprises people: **there are no OAuth scopes anywhere in this flow.** No `scope` claim is being honoured by anything. The narrowing measured further down — a session allowed to fetch an agent card but not to invoke it — happens entirely in IAM, after the token has finished its one job.

| | what it does | where it lives | crosses the boundary? |
|---|---|---|---|
| OIDC token | proves who is calling | minted by the caller's cloud | **yes** |
| `aud` | limits where it can be replayed | caller-chosen claim, pinned by a far-end condition | travels, but proves nothing alone |
| trust policy, federated credential, invoker binding | maps that signature to a local principal | far end, written by you | **no** |
| IAM permissions, session policy | what that principal may do | far end, the vendor's own language | **no** |
| the call chain — on whose behalf | *missing* | — | — |

Four layers, three of them re-authored per cloud in a different dialect, and the fifth does not exist yet. That table is the honest answer to why this is harder than it looks.

#### What a Cloud Identity Means Somewhere Else

Less than the diagrams imply, and everything above follows from it.

When the coordinator presents a Google-signed token to STS, AWS does two things. It fetches Google's public keys from a well-known OIDC discovery endpoint and checks the signature. Then it applies the conditions **you** wrote into the role's trust policy — this audience, this subject.

That is the whole mechanism. AWS learns that a token was signed by whoever holds a key Google published, and that the token says `sub` is some number. It has never heard of your service account, your project or your agent.

**Authentication crosses the boundary. Authorization never does.** The number in that token means what your trust policy says it means and nothing else. Delete the condition and the same valid token authorizes nothing.

So there is no such thing as a cross-cloud identity. There is a locally defined mapping, at each far end, from a foreign signature to a local principal. Three far ends, three mappings — and that count is a property of the boundaries, not of the issuer. Change who signs and you have changed the signature, not the arithmetic.

Hold on to that sentence. It is the whole of the SPIFFE argument later on.

#### Six Edges

Three clouds means six directed cross-cloud edges, and each is settled independently by what the caller can present and what the callee will accept. This mesh runs three of them — it is rooted on GCP, so the GCP-origin rows are what is deployed. The rest come from the reverse-root experiment in the repository and from the vendors' own documentation.

![Six directed edges between three clouds, sourced 25 August 2026, all six keyless. GCP to AWS and GCP to Azure are deployed and controlled, via a metadata JWT to STS AssumeRoleWithWebIdentity and to an Entra federated credential. AWS to GCP is code written but not deployed. AWS to Azure and Azure to GCP are vendor-documented but not built. Azure to AWS follows from both vendors' docs rather than a measurement, the weakest cell.](img/medium/auth-01-six-edges.png)

The evidence column separates what ran against a live cloud with a negative control behind it from what is merely written, and what is written from what only the vendor documents. Two rows are deployed and controlled. The bottom row combines two vendors' documented capabilities and is the weakest cell in the table.

Six edges, six configurations, no two alike.

The cell that closed most recently is AWS to Azure, and it is the reason the mint side can now be called converged. Entra's federated credential wants a JWT assertion from an issuer publishing OIDC discovery. Outside EKS with IRSA, or Cognito, an ECS task role or a Lambda execution role was not one, so that leg fell back to a stored client secret — and a comment in this repository still said so. IAM outbound identity federation gives an account its own OIDC issuer URL with standard discovery endpoints, and a workload obtains a signed JWT by calling `GetWebIdentityToken` with the audience it wants. The comment is now dated, and what looked like a structural asymmetry between vendors turned out to be a gap one of them had not filled yet.

It also corrects a claim these articles used to lean on. AWS's outbound tokens can carry tags that arrive as custom claims, which is how AWS's own guidance propagates user context. Google's metadata identity endpoint takes three query parameters — audience, format and licenses — and emits a fixed claim set, so a GCP-rooted caller cannot put anything of its own in the token it presents. Claim control is a property of the specific minter, not of metadata services in general.

#### What This Mesh Measured

Three research agents on GCP, AWS and Azure, coordinated from Cloud Run. Every outbound leg starts at the same place — the metadata server issues a short-lived OIDC token with whatever audience you ask for — then diverges by cloud. Google ID token to Cloud Run, token to STS `AssumeRoleWithWebIdentity` then SigV4 for AWS, token to an Entra Federated Identity Credential for Azure.

No stored secrets on any of them. Each leg has a positive control and a negative control: run it as deployed, then run it again with the credential removed and confirm it is refused. **A leg that answers is worth nothing until the same leg has denied without its credential.** There is also a wrong-audience probe on the GCP leg, which separates *this identity is checked* from *some token is checked*. Eight probes, all holding.

#### Permissions Narrow Across a Federation Boundary

An inline session policy on `AssumeRoleWithWebIdentity` intersects with the role's own policy and can never widen it, so a session can be scoped below what the role permits, per call rather than per deployment.

![Session policy varied on the AWS leg, measured on the deployed mesh on 25 August 2026. With the session policy allowing GetAgentCard only, the card fetch is allowed and the invocation is refused. With the session policy allowing InvokeAgentRuntime only, the card fetch is refused and the invocation is never reached. Unattenuated, both are allowed. Both refusals name the session policy as the layer that refused.](img/medium/auth-02-attenuation.png)

Neither action substitutes for the other in either direction. Both refusals name the session policy as the layer that refused, which distinguishes an attenuation refusal from a role refusal without guessing. The invoke-only run is what proves discovery genuinely succeeded in the card-only run rather than being skipped.

There is a generalisation here that is more useful than the measurement. **On all three clouds, discovery is authorized separately from invocation.** Fetching an agent card is its own action with its own permission, which is why the credential in this mesh is attached to the httpx *client* rather than to one request — get that wrong and the card fetch fails while the invoke looks correctly configured.

Of the three things agent-identity articles ask for, per-call attenuation is the one a deployment can demonstrate rather than assert.

#### Why SPIFFE and SPIRE Do Not Fix This

Ask what to do about cross-cloud agent identity and you get pointed at SPIFFE and SPIRE. The recommendation is sound for the problem it was designed against and does not transfer to this one, and the reason compresses to a sentence.

**SPIRE changes who signs your token. It does not change the fact that AWS, Azure and Google each decide, locally and separately, what that signature is allowed to do.**

SPIFFE gives every workload a passport your organisation issues and recognises. But calling AWS is not showing a passport, it is crossing a border. Each cloud requires a visa, and the visa rules are written by the destination. AWS still needs a trust policy naming a subject and an audience. Entra still needs a federated credential. Cloud Run still needs an invoker binding. Adopt SPIRE and you write all three exactly as before — you have upgraded the passport, and the visa count was never a property of the passport. Two of those borders admit only their own passports, so on the Cloud Run and Container Apps legs a SPIFFE credential is not usable at all.

Some of this is a category error about the word multicloud, which does double duty. **Meaning A** is my workloads, spread across clouds: clusters on EKS, GKE and AKS, one organisation, one administrative boundary, both ends of every call yours. **Meaning B** is my agent, calling other vendors' services: you own one end, the others are managed runtimes with their own idea of a valid caller, and there are three trust domains of which you administer one. SPIFFE was built for the first. "SPIFFE is good for multicloud" is true of meaning A and gets repeated as though it were true of meaning B.

![Adopting SPIRE on a serverless agent mesh. The token minter goes from a managed metadata server to a SPIRE Server you run. Attestation on serverless goes from built into the runtime to an open RFC since 2020. Public endpoints to operate goes from none to OIDC discovery on your own DNS. Federations still required stays at three. Places identity is pinned goes from three to one. Control over token claims goes from none to yours.](img/medium/auth-04-spire-cost.png)

The deeper problem is that the passport would also be worse here. SPIFFE's value is **attestation** — an identity bound to something observed about the running workload, which SPIRE does with an agent on a stable node. Serverless has no stable node. Cloud Run creates an instance for a burst of traffic and destroys it, and the service scales to zero between runs. The RFC for serverless support, `spiffe/spire` issue 1843, has been open since September 2020, and what it proposes to attest *with* is the metadata token you already hold.

So the workable design is the obvious one: run the SPIRE server on a VM, have the coordinator present its Cloud Run metadata token, and get back a JWT-SVID with whatever claims you want. Look at what that is. The server observed nothing. It received a Google token and re-signed its claims under a new name, so the SPIFFE ID means exactly what the Google token meant — that is the only evidence in the chain. You have added a signing hop and produced an identity weaker than the one it wrapped.

It also spends the two properties the mesh was built for. **No long-lived secrets:** today there are none, and the CA signing key would become the best secret in the building, since holding it mints identities AWS and Entra accept for your roles while the metadata server they think they are trusting is never consulted. **Independence:** today the three legs fail independently, and with SPIRE both AWS and Entra validate your SVID by fetching a JWKS over the public internet, so every cross-cloud call gains a shared dependency on one endpoint you run, on DNS you manage, behind a certificate you renew. Multicloud is supposed to buy independence. This spends it.

SPIFFE Federation is not the escape hatch either. It exchanges trust bundles between SPIFFE trust domains, and needs the far side to be one, publishing a SPIFFE bundle endpoint. AWS is not. Neither is Azure, nor Google.

**Where it is the right call** is meaning A, and the case is stronger than the space it gets here. On Kubernetes nearly every objection above disappears: nodes exist so the identity is genuinely attested rather than re-signed, the Workload API is a Unix socket beside the workload so there is no public endpoint in the credential path, and workload attestation can distinguish a pod, a service account and a container image — finer than any cloud service account. At scale the arithmetic reverses, because three identities across three clouds is a script and fifty microservices with per-service identities is not. And X.509-SVIDs give you mutual TLS, which none of the three clouds' federation primitives provide. The claim here is narrow and worth stating as such: SPIRE is the wrong tool for a serverless agent mesh calling managed runtimes on three vendors.

#### The Prior Art is Better Than the Discourse

Search for agent identity and you get opinion pieces. The engineering exists, filed in three places that do not cite each other.

**The protocol work split the problem correctly, into a credential and a chain.** The IETF WIMSE working group is chartered for least-privilege access control for workloads across multiple platforms, with an architecture draft, a Workload Identifier, Workload Credentials, and a Workload Proof Token binding a workload's authentication to a specific HTTP request. Its Workload Identity Practices draft documents the Instance Metadata Endpoint as an established industry pattern, listed beside SPIFFE rather than as the thing SPIFFE replaces. It also carries a requirement worth auditing against: a credential for internal platform access should not be reused to federate to an external STS, because that conflates trust and audience boundaries. This mesh mints a separate token per destination, so it passes.

OAuth Transaction Tokens cover the other half — short-lived signed JWTs carrying user identity, workload identity and authorization context along a call chain, issued through a profile of the OAuth 2.0 Token Exchange endpoint and cryptographically protected so downstream workloads cannot alter what they were handed. This is the microservices industry having already learned the lesson: passing the caller's access token down the chain does not work, and the fix was a separate token for the chain, not a better credential for the workload. The agent extension, using `sub` for the principal and `act` for the agent acting, expired in April 2026 and was replaced by an individual submission. Specified, not shipped.

**The governance frameworks say what, not how.** The Cloud Security Alliance has an Agentic AI Identity and Access Management paper and an Agent Identity Governance Framework. The OWASP Top 10 for Agentic Applications 2026 treats agents as operational actors with delegated authority, and two of its categories are Identity and Privilege Abuse, and Insecure Inter-Agent Communication. NIST issued an RFI on AI Agent Security in early 2026 and a concept paper on AI Agent Identity and Authorization. None of them tells you which token goes in which header.

**And the products are where cross-cloud actually shows up.**

![Vendor agent identity in 2026. Bedrock AgentCore Identity is generally available, an inbound authorizer plus an outbound token vault. Microsoft Entra Agent ID is in preview, treating agents as directory objects under Conditional Access. Vertex AI Agent Engine identities have shipped, inside Google's agent runtime. Three registries, no interoperable protocol between them, and cross-cloud works where one vendor has chosen to support another.](img/medium/auth-05-vendor-products.png)

They address cross-cloud bilaterally. Microsoft documents securing a Bedrock agent with Entra Agent ID and surfacing agents from Bedrock, Vertex and Databricks in one registry. AWS documents Entra as an inbound identity provider for AgentCore Runtime and Gateway. Every one of those is a vendor integration, not a federation — each cloud keeps its own registry and its own mapping, and it works because one vendor decided to support another. Nobody fills a quadratic matrix by negotiation, and the cells that stay empty are the ones where two vendors have no commercial reason to care about each other's workloads.

Worth noting against the discourse these products are sold into: AgentCore's outbound Microsoft credential provider is configured with a stored client secret. It is a different mechanism from outbound identity federation — OAuth access to Microsoft resources rather than workload identity, so the two are not in conflict — but the same vendor that ships a keyless way to authenticate to Entra configures that leg of its agent identity service with a secret anyway. No cloud has this finished.

#### What to Build Instead

Follow the split the standards made. A credential identifies the workload. A separate token carries the chain.

**Layer one, who is calling.** Keep the metadata mint. It is attested by the only party positioned to attest anything on serverless, costs nothing to run, and WIMSE documents it as an established pattern rather than a shortcut. Enforce audience separation: one token per destination, and never reuse a platform-internal credential against an external STS.

**Layer two, on whose behalf and through whom.** A Transaction Token Service at the edge takes the incoming request and whatever authenticated the requester, and issues a short-lived signed JWT with `sub` for the principal and `act` for the agent acting. Each agent presents it and requests a new one to call the next hop, so the chain accumulates rather than being asserted. It is separate from the credential, so it is unaffected by three clouds each dictating their own credential format — and unlike a SPIRE server it is not in the credential path, so if it is down you stop starting new work and no cloud is fetching keys from you to validate a login.

**Layer three, carried by the protocol.** A2A added an extension mechanism in v1.0.1, and the Secure Passport extension defines a `CallerContext` attached beside the task with a client identifier, state and a signature. Use the extension as the envelope and a transaction token as the payload, and the two gaps cancel. Declare it on the agent card too — A2A carries `securitySchemes` in OpenAPI 3 shape plus a `security` block mapping scopes to individual skills, and most deployments declare far less than the spec allows.

**Layer four, narrowing per hop.** The attenuation measurement above is that layer working.

And the two-afternoon version, if none of that is happening this quarter. Put a requester field on the run record, because until a run carries who asked for it the audit trail names the coordinator as the actor for everything. Then use `RoleSessionName` — required on every `AssumeRoleWithWebIdentity` call, caller's choice, two to sixty-four characters, and it lands in CloudTrail. It is the only caller-supplied identity string in this mesh that reaches a cloud provider's audit log, and it is currently a constant.

#### Two Operational Findings, and One Embarrassment

Cloud Run returns **401** when there is no usable ID token — wrong audience, an OAuth access token, malformed — and **403** when the token is fine and the identity lacks `roles/run.invoker`. Reading 401 as a denial conflates a client bug with an authorization result. The AWS equivalent is worth the same care: `InvalidIdentityToken` means the token could not be validated at all, `AccessDenied` means your trust conditions did not match, and that distinction separates a provider-setup bug from a condition bug.

**IAM revocation takes about two minutes to propagate.** Anonymous requests kept succeeding for that long after a binding was removed, with the policy already reading correctly. A control run immediately after a revocation reports the hole still open and sends someone looking for a second cause that does not exist.

The reason I know is the embarrassment. Reviewing this project for these articles turned up its own coordinator open to the internet on a public invoker binding, serving a container that holds federated credentials for three clouds — and an anonymous health endpoint disclosing the AWS account number, the full runtime ARN, the Azure FQDN and every leg's auth mode. Earlier, the Azure agent's negative control answered without a credential at all, because the deploy sequence used had skipped the step that enforces Entra on the ingress. Both were found by the controls. The second was found four days after it was introduced, which is an argument for running them on a schedule rather than before a write-up.

Every positive signal in this project was green while one of three agents was open to the world. That is the entire justification for negative controls.

#### Summary

Cross-cloud agent auth is quadratic. Three clouds is six directed edges, four is twelve, and each cell is the intersection of one cloud's mint format with another cloud's accept rules.

The mint side has converged: all three clouds issue an OIDC JWT with a caller-chosen audience to a workload holding no secret. The accept side has not, and that is where the whole count comes from. One ingress validates a token from any OIDC issuer; two require an issuer they own. Plain OIDC validation is the baseline here, not an achievement — the gap is two products that have not adopted it, and closing it is a product change rather than an industry-wide adoption of anything.

The token itself does less than people assume. It authenticates, it carries a replay boundary in its audience, and it carries no permissions whatsoever. Authentication crosses the boundary; authorization never does. Each far end decides locally what a foreign signature may do, so the mapping exists once per boundary no matter who signs — which is why SPIFFE and SPIRE do not help. Change the issuer and you have changed the signature, not the arithmetic, while adding a server, a public endpoint and a CA key to a mesh that had none.

What is missing is narrower than the discourse suggests, and the standards already split it correctly: a credential identifies the workload, and a separate token carries the call chain. The first exists on every cloud today. The second is drafted, and not yet shipped by anyone.
