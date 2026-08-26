#!/usr/bin/env python3
"""Render every table in the cross-cloud auth article as a PNG.

Medium does not render markdown tables at all, so the Medium version of
`docs/article-medium-auth.md` carries images where the dev.to versions carry
tables. This script is where those images come from.

The typesetting helpers are imported from `make_medium_graphics`, which is
guarded by `__main__` and so does not render its own article's images on
import. Sharing the helper rather than copying it is the point: the two
articles' tables then wrap, rule and align identically, and a fix to the wrap
budget lands on both.

**Every value below is hard-coded here.** Sources, all dated 2026-08-25:

    six-edge table        docs/INTEROP.md and coordinator/aws_origin.py
    attenuation results   docs/INTEROP.md, measured on the deployed mesh
    ingress acceptance    each vendor's own inbound-auth documentation
    SPIRE comparison      docs/INTEROP.md
    vendor products       vendor launch documentation

An image is the one place in this repo where a stale number cannot be caught by
grep. If a measurement changes, change it here too.

    uv pip install --system matplotlib
    python3 docs/img/make_auth_graphics.py
"""

from make_medium_graphics import table


def six_edges():
    """The quadratic problem in one table.

    The evidence column is load-bearing and deliberately says four different
    things. Two rows ran against the live cloud with a negative control behind
    them; one is code in this repository that has not been run; two are the
    vendor's own documentation; and the last is two vendors' documented
    capabilities combined, which is the weakest cell here and is labelled as
    such in the prose.
    """
    table(
        "auth-01-six-edges",
        "Six directed edges between three clouds",
        "Each cell is one cloud's mint format meeting another cloud's accept "
        "rules. Neither is standardised, so no two are configured alike. "
        "Measured and sourced 2026-08-25.",
        columns=["edge", "mechanism", "keyless", "evidence"],
        rows=[
            ["`GCP -> AWS`", "metadata JWT to STS AssumeRoleWithWebIdentity",
             "yes", "deployed and controlled"],
            ["`GCP -> Azure`", "metadata JWT to an Entra federated credential",
             "yes", "deployed and controlled"],
            ["`AWS -> GCP`", "signed GetCallerIdentity to Google STS",
             "yes", "code written, not deployed"],
            ["`AWS -> Azure`", "STS GetWebIdentityToken to an Entra credential",
             "yes", "vendor-documented, not built"],
            ["`Azure -> GCP`", "Entra JWT to a Google workload identity pool",
             "yes", "vendor-documented, not built"],
            ["`Azure -> AWS`", "Entra JWT to an IAM OIDC provider",
             "yes", "*follows from both vendors' docs*"],
        ],
        widths=[0.0, 0.20, 0.62, 0.74],
    )


def attenuation():
    """The one rule of the three that a deployment can demonstrate.

    Both directions matter and the second row is what makes the first
    believable: when discovery is the narrowed action the leg never reaches the
    invocation, which is how you know the card fetch in row one genuinely
    succeeded rather than being skipped.
    """
    table(
        "auth-02-attenuation",
        "Session policy varied on the AWS leg",
        "An inline session policy on AssumeRoleWithWebIdentity intersects with "
        "the role and can never widen it. Deployed mesh, 2026-08-25. Both "
        "refusals name the session policy as the layer that refused.",
        columns=["session policy allows", "card fetch", "invocation"],
        rows=[
            ["`GetAgentCard` only", "allowed", "*refused*"],
            ["`InvokeAgentRuntime` only", "*refused*", "not reached"],
            ["unattenuated", "allowed", "allowed"],
        ],
        widths=[0.0, 0.42, 0.68],
    )


def ingress():
    """Where the quadratic count actually comes from.

    All three clouds now mint an OIDC JWT with a caller-chosen audience, so the
    asymmetry is entirely here.
    """
    table(
        "auth-03-ingress",
        "Will the ingress accept a foreign issuer?",
        "Every cloud can mint an OIDC JWT for a workload holding no secret. "
        "One of the three will validate a token from an issuer it does not "
        "own. Vendor documentation, 2026-08-25.",
        columns=["runtime", "inbound auth", "foreign issuer"],
        rows=[
            ["Bedrock AgentCore",
             "SigV4, or a custom JWT authorizer taking any OIDC issuer",
             "yes"],
            ["Azure Container Apps", "Entra on the ingress", "*Entra only*"],
            ["Cloud Run",
             "IAM invoker check against a Google-signed ID token",
             "*Google only*"],
        ],
        widths=[0.0, 0.24, 0.80],
    )


def spire_cost():
    """What adopting SPIRE on this shape of deployment actually changes.

    The federations row is the one people skip when costing it out.
    """
    table(
        "auth-04-spire-cost",
        "Adopting SPIRE on a serverless agent mesh",
        "SPIRE changes which issuer the three clouds trust. It does not reduce "
        "how many of them there are, and configuring them is the work.",
        columns=["item", "today", "with SPIRE"],
        rows=[
            ["token minter", "managed metadata server", "SPIRE Server you run"],
            ["attestation on serverless", "built into the runtime",
             "*open RFC since 2020*"],
            ["public endpoints to operate", "none", "*OIDC discovery, on your DNS*"],
            ["federations still required", "3", "*3*"],
            ["places identity is pinned", "3", "1"],
            ["control over token claims", "none", "yours"],
        ],
        widths=[0.0, 0.34, 0.66],
    )


def vendor_products():
    """All three clouds shipped agent identity in 2026.

    Each is a registry inside one boundary, with bilateral integrations bolted
    on. That is the same structure as the trust policies underneath, one layer
    up.
    """
    table(
        "auth-05-vendor-products",
        "Vendor agent identity, 2026",
        "Three registries, no interoperable protocol between them. Cross-cloud "
        "works where one vendor has chosen to support another.",
        columns=["product", "status", "shape"],
        rows=[
            ["Bedrock AgentCore Identity", "GA",
             "inbound authorizer plus an outbound token vault"],
            ["Microsoft Entra Agent ID", "preview",
             "agents as directory objects, Conditional Access"],
            ["Vertex AI Agent Engine identities", "shipped",
             "agent identities inside Google's agent runtime"],
        ],
        widths=[0.0, 0.32, 0.48],
    )


if __name__ == "__main__":
    print("rendering:")
    six_edges()
    attenuation()
    ingress()
    spire_cost()
    vendor_products()
    print("done.")
