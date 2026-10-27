# Retail Store on Amazon EKS

An AWS deployment project for a containerized retail application. This repository brings together Terraform-managed infrastructure, Kubernetes Helm charts, and Argo CD so the application can be deployed to Amazon EKS with a GitOps workflow.

> **Project work:** This repository adapts the AWS Containers Retail Store sample with an EKS Auto Mode deployment, Terraform infrastructure, Argo CD configuration, and deployment documentation. The application services are based on the upstream [AWS Containers Retail Store sample](https://github.com/aws-containers/retail-store-sample-app); see the project license and service attribution files for details.

## What’s Included

- **AWS infrastructure:** Terraform provisions a VPC, public and private subnets, and an EKS Auto Mode cluster.
- **Cluster add-ons:** EKS Blueprints Add-ons installs NGINX Ingress and cert-manager. Terraform installs Argo CD and applies the Argo CD project and application manifests.
- **Retail application:** UI, catalog, cart, checkout, and orders services, each with its own source and Helm chart under `src/`.
- **GitOps deployment:** Argo CD tracks the configured Git repository and deploys the Helm charts into the `retail-store` namespace.

## Architecture

```text
Browser
  |
Network Load Balancer -> NGINX Ingress -> Retail Store services
                                           | UI
                                           | Catalog
                                           | Cart
                                           | Checkout -> Orders

Terraform -> VPC + EKS Auto Mode + add-ons + Argo CD
                                          |
                                          +-> Argo CD Applications -> Helm charts in src/
```

| Service | Implementation | Location |
| --- | --- | --- |
| UI | Java | [`src/ui`](src/ui/) |
| Catalog | Go | [`src/catalog`](src/catalog/) |
| Cart | Java | [`src/cart`](src/cart/) |
| Checkout | Node.js | [`src/checkout`](src/checkout/) |
| Orders | Java | [`src/orders`](src/orders/) |

## Deploy

### Requirements

- An AWS account and AWS CLI authenticated with a suitably scoped IAM identity. Do not use root-user credentials.
- Terraform, kubectl, and Git.
- Permissions to create the VPC, EKS cluster, IAM resources, and related AWS resources. EKS and NAT Gateway resources incur charges while running.

### 1. Clone and configure Argo CD

```bash
git clone https://github.com/ravirajpatil198/retail-store.git
cd retail-store
```

Before deployment, update the `repoURL` in every file under `argocd/applications/` and the `sourceRepos` entry in `argocd/projects/retail-store-project.yaml` to:

```text
https://github.com/ravirajpatil198/retail-store.git
```

The checked-in manifests currently reference the upstream repository. Updating these URLs lets Argo CD deploy the charts from your repository instead.

### 2. Provision AWS infrastructure

```bash
cd terraform
terraform init
terraform plan
terraform apply
```

Terraform uses `us-west-2` by default and adds a random suffix to the cluster name. Review the plan and costs before applying. Set variables as needed, for example:

```bash
terraform apply -var="aws_region=us-east-1" -var="environment=dev"
```

### 3. Connect to the cluster

Use the cluster name and region reported by Terraform outputs:

```bash
aws eks update-kubeconfig --region <aws-region> --name <cluster-name>
kubectl get nodes
kubectl get applications -n argocd
```

Argo CD synchronizes the configured applications. Check application and workload status with:

```bash
kubectl get applications -n argocd
kubectl get pods -n retail-store
kubectl get svc -n ingress-nginx
```

The NGINX ingress service is exposed using an AWS Network Load Balancer. Retrieve its hostname with:

```bash
kubectl get svc ingress-nginx-controller -n ingress-nginx
```

### Argo CD UI

```bash
kubectl port-forward svc/argocd-server -n argocd 8080:443
```

Open `https://localhost:8080`. Retrieve the initial admin password with:

```bash
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 --decode
```

## Configuration

Terraform inputs are defined in [`terraform/variables.tf`](terraform/variables.tf). Defaults include the `retail-store` cluster name, Kubernetes `1.33`, a `10.0.0.0/16` VPC, and a single NAT Gateway. A single NAT Gateway lowers cost but is not a production high-availability configuration.

Application routing and service configuration are defined in [`src/app/chart/values.yaml`](src/app/chart/values.yaml). Argo CD project and application manifests are in [`argocd/`](argocd/).

## CI/CD Scope

Argo CD is configured for automated synchronization of Kubernetes resources from Git. This repository does not include GitHub Actions workflows or an automated image-build-and-push pipeline; service image build and publishing must be configured separately if required.

## Remove Resources

From the `terraform/` directory, remove resources created by this configuration with:

```bash
terraform destroy
```

Review the destroy plan first. Confirm no data or resources you need will be removed.

## License and Attribution

This project is distributed under the license in [`LICENSE`](LICENSE). The retail application is based on the AWS Containers sample; upstream notices and third-party dependency attributions are retained in the service directories.
