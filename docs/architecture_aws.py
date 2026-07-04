"""Render the PursuitDesk AWS architecture diagram as PNG and SVG."""

import base64
import mimetypes
import xml.etree.ElementTree as ET
from pathlib import Path

from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import Lambda
from diagrams.aws.database import Dynamodb, RDSPostgresqlInstance
from diagrams.aws.integration import EventbridgeScheduler
from diagrams.aws.management import Cloudwatch
from diagrams.aws.ml import Bedrock
from diagrams.aws.network import APIGateway
from diagrams.aws.security import IdentityAndAccessManagementIamRole, SecretsManager
from diagrams.onprem.ci import GithubActions
from diagrams.onprem.client import User
from diagrams.onprem.network import Internet
from diagrams.saas.cdn import Cloudflare
from diagrams.saas.payment import Stripe


OUTPUT_PATH = Path(__file__).with_name("architecture_aws")
SVG_PATH = OUTPUT_PATH.with_suffix(".svg")
SVG_NAMESPACE = "http://www.w3.org/2000/svg"
XLINK_NAMESPACE = "http://www.w3.org/1999/xlink"

GRAPH_ATTR = {
    "bgcolor": "#F8FAFC",
    "dpi": "160",
    "fontcolor": "#0F172A",
    "fontname": "Arial Bold",
    "fontsize": "22",
    "labeljust": "l",
    "labelloc": "t",
    "nodesep": "0.55",
    "pad": "0.35",
    "ratio": "fill",
    "ranksep": "0.9",
    "size": "16,9!",
}

NODE_ATTR = {
    "fontcolor": "#1E293B",
    "fontname": "Arial",
    "fontsize": "10",
    "height": "1.0",
}

EDGE_ATTR = {
    "color": "#64748B",
    "fontcolor": "#475569",
    "fontname": "Arial",
    "fontsize": "9",
    "penwidth": "1.5",
}

AWS_CLUSTER = {
    "bgcolor": "#FFF7ED",
    "color": "#FDBA74",
    "fillcolor": "#FFF7ED",
    "fontcolor": "#9A3412",
    "fontname": "Arial Bold",
    "fontsize": "15",
    "margin": "18",
    "penwidth": "1.4",
    "style": "rounded,filled",
}

VPC_CLUSTER = {
    "bgcolor": "#F0FDF4",
    "color": "#22C55E",
    "fillcolor": "#F0FDF4",
    "fontcolor": "#166534",
    "fontname": "Arial Bold",
    "fontsize": "12",
    "margin": "16",
    "penwidth": "1.3",
    "style": "rounded,filled",
}

SERVICE_CLUSTER = {
    "bgcolor": "#FFFFFF",
    "color": "#CBD5E1",
    "fillcolor": "#FFFFFF",
    "fontcolor": "#334155",
    "fontname": "Arial Bold",
    "fontsize": "12",
    "margin": "16",
    "style": "rounded,filled",
}

EXTERNAL_CLUSTER = {
    "bgcolor": "#EFF6FF",
    "color": "#93C5FD",
    "fillcolor": "#EFF6FF",
    "fontcolor": "#1D4ED8",
    "fontname": "Arial Bold",
    "fontsize": "12",
    "margin": "18",
    "style": "rounded,filled",
}


def render() -> None:
    with Diagram(
        "PursuitDesk | AWS Architecture",
        filename=str(OUTPUT_PATH),
        direction="LR",
        outformat=["png", "svg"],
        show=False,
        graph_attr=GRAPH_ATTR,
        node_attr=NODE_ATTR,
        edge_attr=EDGE_ATTR,
    ):
        advisor = User("GovCon advisor")

        with Cluster("Web delivery", graph_attr=EXTERNAL_CLUSTER):
            pages = Cloudflare("Cloudflare Pages\nstatic frontend")
            frontend_ci = GithubActions("GitHub Actions\nfrontend deploy")

        with Cluster("AWS edge | us-east-1", graph_attr=AWS_CLUSTER):
            gateway = APIGateway("HTTP API\nJWT authorizer\n(optional)")

        with Cluster("AWS dual-stack VPC | 2 subnets | no NAT", graph_attr=VPC_CLUSTER):
            api = Lambda("API Lambda\nFastAPI + Mangum")
            private_upsert = Lambda("Private upsert\n+ enrichment")
            postgres = RDSPostgresqlInstance("RDS PostgreSQL 15\npgvector | private")

        with Cluster("AWS async AI", graph_attr=AWS_CLUSTER):
            proposal_writer = Lambda("Proposal Writer\nasync Lambda")
            proposal_jobs = Dynamodb("DynamoDB\njob history + TTL")
            bedrock = Bedrock("Amazon Bedrock\ndrafts + helpers")

        with Cluster("AWS ingestion | optional schedules", graph_attr=AWS_CLUSTER):
            scheduler = EventbridgeScheduler("EventBridge\nScheduler")
            public_fetch = Lambda("Public fetch\nLambdas")

        with Cluster("AWS operations & security", graph_attr=AWS_CLUSTER):
            secrets = SecretsManager("Secrets Manager\nconfigured refs")
            cloudwatch = Cloudwatch("CloudWatch\n7-day logs\nalarms optional")
            iam = IdentityAndAccessManagementIamRole("IAM roles\nruntime access")
            iam >> Edge(style="invis") >> secrets >> Edge(style="invis") >> cloudwatch

        with Cluster("External services", graph_attr=EXTERNAL_CLUSTER):
            source_apis = Internet("SAM.gov\nUSAspending\nGSA CALC+")
            stripe = Stripe("Stripe\nbilling optional")
            source_apis >> Edge(style="invis") >> stripe

        advisor >> Edge(label="HTTPS", color="#2563EB", penwidth="2.0") >> pages
        pages >> Edge(label="JSON / HTTPS", color="#2563EB", penwidth="2.0") >> gateway
        frontend_ci >> Edge(label="Wrangler deploy", style="dashed", constraint="false") >> pages

        gateway >> Edge(label="API routes", color="#F97316", penwidth="2.0") >> api
        api >> Edge(label="SQL", color="#16A34A", penwidth="2.0") >> postgres

        gateway >> Edge(label="proposal routes", color="#F97316", penwidth="2.0") >> proposal_writer
        proposal_writer >> Edge(label="job state", color="#7C3AED") >> proposal_jobs
        proposal_writer >> Edge(label="model calls", color="#7C3AED") >> bedrock

        scheduler >> Edge(label="triggers", style="dashed") >> public_fetch
        public_fetch >> Edge(label="async invoke") >> private_upsert
        private_upsert >> Edge(label="normalized data", color="#16A34A") >> postgres

        source_apis >> Edge(label="public HTTPS") >> public_fetch
        api >> Edge(label="checkout / webhook", style="dashed", constraint="false") >> stripe

        secrets >> Edge(label="optional reads", style="dotted", arrowhead="none", constraint="false") >> api
        iam >> Edge(label="runtime permissions", style="dotted", arrowhead="none", constraint="false") >> api
        proposal_writer >> Edge(label="Lambda logs + metrics", style="dotted") >> cloudwatch

    _embed_svg_images(SVG_PATH)


def _embed_svg_images(svg_path: Path) -> None:
    """Replace Graphviz's local icon paths with portable data URIs."""
    ET.register_namespace("", SVG_NAMESPACE)
    ET.register_namespace("xlink", XLINK_NAMESPACE)
    tree = ET.parse(svg_path)
    href_key = f"{{{XLINK_NAMESPACE}}}href"

    for image in tree.getroot().iter(f"{{{SVG_NAMESPACE}}}image"):
        href = image.get(href_key, "")
        if not href or href.startswith("data:"):
            continue
        icon_path = Path(href)
        if not icon_path.is_file():
            raise FileNotFoundError(f"SVG icon was not generated locally: {icon_path}")
        media_type = mimetypes.guess_type(icon_path.name)[0] or "application/octet-stream"
        payload = base64.b64encode(icon_path.read_bytes()).decode("ascii")
        image.set(href_key, f"data:{media_type};base64,{payload}")

    tree.write(svg_path, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    render()
