# Jenkins CI/CD Setup — Start to Finish

This guide configures Jenkins for this repository: it tests the five services,
builds and publishes their images to private Amazon ECR repositories, updates
the service Helm values in Git, and lets Argo CD deploy the changes to EKS.

The pipeline is defined in [`Jenkinsfile`](./Jenkinsfile); its shorter
companion is [`JENKINS.md`](./JENKINS.md). Jenkins does **not** deploy directly
to Kubernetes or need cluster-admin credentials.

## 1. Understand the deployment flow

1. A change is pushed to GitHub and starts a Jenkins multibranch build.
2. Jenkins lints the Helm charts and tests the Go, Java, and Node.js services.
3. On `main`, when files under `src/` change (or the job runs for the first
   time), Jenkins reads the release version from
   `src/app/chart/Chart.yaml` and pushes five SemVer-tagged images to ECR.
4. Jenkins updates the five service chart values and pushes a GitOps commit to
   `main`.
5. Argo CD sees the values commit and syncs the Helm releases to EKS.

Branches other than `main` run validation only. Jenkins-generated service
`values.yaml` commits do not publish images again, so the GitOps commit does
not create an image-publish loop. The pipeline tests still run on that commit.
For each release, bump the umbrella chart version in
`src/app/chart/Chart.yaml` using `MAJOR.MINOR.PATCH` (for example, `1.2.5` to
`1.2.6`). Do not reuse a version for different source code.

## 2. Decide the AWS and GitHub settings

Record these values before configuring anything:

| Setting | Example | Used by |
| --- | --- | --- |
| AWS region | `us-west-2` | ECR, EKS, and Jenkins environment |
| AWS account ID | `123456789012` | ECR registry address and Jenkins environment |
| GitHub repository SSH/HTTPS URL | `https://github.com/OWNER/REPOSITORY.git` | Jenkins SCM and Argo CD |
| GitOps branch | `main` | Jenkins push and Argo CD tracking |
| EKS cluster name | Terraform output | EKS and kubectl |

Use the **same repository and branch** throughout. Do not copy the example
account ID into a real configuration.

### Important: reconcile the repository URLs first

The checked-in Argo CD application manifests currently use
`https://github.com/ravirajpatil198/retail-store.git`, while
[`argocd/projects/retail-store-project.yaml`](./argocd/projects/retail-store-project.yaml)
allows `https://github.com/LondheShubham153/retail-store-sample-app`. These
URLs must match the repository Jenkins checks out, or Argo CD may be unable to
read the application source.

Before deploying the Terraform configuration:

1. Choose the actual repository URL to use (usually the URL configured in the
   Jenkins multibranch job).
2. Update `repoURL` in **all five** files under
   [`argocd/applications/`](./argocd/applications) to that URL.
3. Update `sourceRepos` in
   [`argocd/projects/retail-store-project.yaml`](./argocd/projects/retail-store-project.yaml)
   to allow that same URL.
4. Keep `targetRevision: main` in all five applications, unless intentionally
   changing both the Jenkins push branch and pipeline condition.

The Jenkinsfile pushes to the `origin` remote populated by the SCM checkout.
Confirm that this remote points to the same repository Argo CD tracks.

## 3. Prepare the AWS environment and deploy EKS

You need an AWS account with permission to create the Terraform resources,
including a VPC, NAT gateway(s), EKS, add-ons, and Argo CD. These resources
can incur ongoing AWS charges.

The Terraform AWS provider in
[`terraform/versions.tf`](./terraform/versions.tf) uses the AWS CLI profile
named `terraform`. Configure that profile with an authorized operator identity
(prefer IAM Identity Center or another short-lived credential mechanism):

```bash
aws configure sso --profile terraform
aws sso login --profile terraform
aws sts get-caller-identity --profile terraform
```

From the repository root, initialize and apply Terraform:

```bash
export AWS_PROFILE=terraform
cd terraform
terraform init
terraform validate
terraform plan
terraform apply
```

Review the plan and approve the apply. The cluster name gets a random suffix.
Save the outputs; in particular, get the actual cluster name and configure
kubectl:

```bash
terraform output -raw cluster_name
aws eks update-kubeconfig \
  --profile terraform \
  --region us-west-2 \
  --name "$(terraform output -raw cluster_name)"
kubectl get nodes
kubectl get applications -n argocd
```

Replace `us-west-2` with the region selected for this deployment. Terraform
installs Argo CD and applies the application/project manifests, so fix the
repository URL mismatch in step 2 before running `terraform apply`.
Keep `AWS_PROFILE=terraform` set in operator terminals for the AWS CLI commands
below, including the kubeconfig credential plugin. Jenkins uses its agent IAM
role instead of this operator profile.

## 4. Create the five immutable ECR repositories

Create the repositories in the **same account and region** Jenkins will use.
The pipeline expects these exact names and uses the `version` in
`src/app/chart/Chart.yaml` as the image tag. Use a stable SemVer
`MAJOR.MINOR.PATCH` value, such as `1.2.5`:

```bash
export AWS_REGION=us-west-2
for service in ui catalog cart checkout orders; do
  aws ecr create-repository \
    --region "$AWS_REGION" \
    --repository-name "retail-store-$service" \
    --image-tag-mutability IMMUTABLE \
    --image-scanning-configuration scanOnPush=true
done
```

If a repository already exists, `create-repository` returns an error for that
repository; verify its name, region, and tag mutability rather than deleting
and recreating it. Set the account ID for Jenkins:

```bash
aws sts get-caller-identity --query Account --output text
```

The registry address has this format:
`<AWS_ACCOUNT_ID>.dkr.ecr.<AWS_REGION>.amazonaws.com`.

## 5. Configure AWS permissions without static keys

### Jenkins agent role

Attach an IAM role to the Jenkins **agent** (for example, the EC2 instance
profile when the agent runs on EC2). Do not put AWS access keys in the
repository, Jenkinsfile, or Jenkins job parameters. The role needs:

- `ecr:GetAuthorizationToken` on `*`.
- For the five ECR repository ARNs in the selected account and region:
  `ecr:DescribeImages`, `ecr:BatchCheckLayerAvailability`,
  `ecr:InitiateLayerUpload`, `ecr:UploadLayerPart`,
  `ecr:CompleteLayerUpload`, and `ecr:PutImage`.

Example policy (replace the region and account ID):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "ecr:GetAuthorizationToken",
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ecr:DescribeImages",
        "ecr:BatchCheckLayerAvailability",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload",
        "ecr:PutImage"
      ],
      "Resource": [
        "arn:aws:ecr:us-west-2:123456789012:repository/retail-store-ui",
        "arn:aws:ecr:us-west-2:123456789012:repository/retail-store-catalog",
        "arn:aws:ecr:us-west-2:123456789012:repository/retail-store-cart",
        "arn:aws:ecr:us-west-2:123456789012:repository/retail-store-checkout",
        "arn:aws:ecr:us-west-2:123456789012:repository/retail-store-orders"
      ]
    }
  ]
}
```

This is a scoped starting policy for the actions in this pipeline. Keep the
role's trust policy restricted to the agent host/service and review permissions
against your organization's policies.

### EKS image-pull access

The service charts currently specify an image-pull secret named `regcred`.
When Jenkins switches the service images from public ECR to private ECR, pods
must be able to authenticate to the private registry. Prefer granting the EKS
Auto Mode node role the required ECR pull permissions (at least
`ecr:GetAuthorizationToken`, `ecr:BatchCheckLayerAvailability`,
`ecr:BatchGetImage`, and `ecr:GetDownloadUrlForLayer`) and removing the
`imagePullSecrets: - name: regcred` setting from all five service chart
`values.yaml` files. Otherwise provision and maintain the referenced secret in
the `retail-store` namespace using an approved credential-refresh mechanism.
ECR authorization tokens expire; a manually created token secret is not a
durable production solution.

## 6. Prepare the Jenkins build node

The Jenkinsfile currently uses valid Declarative Pipeline syntax, `agent any`.
That means Jenkins runs the build on any available executor. If you only have
the built-in controller node, the build can run there **only if** that node has
an executor enabled. The node running the build must be Linux, and it must have
all required tools and AWS permissions.

For production, use a dedicated Linux build agent rather than the controller:
it isolates the controller from Docker access, builds, and untrusted job code.
For that configuration, change the first lines of `Jenkinsfile` to:

```groovy
pipeline {
  agent { label 'linux-docker' }
```

Then create an online agent with label `linux-docker`. Do not apply that label
change if you intend to run on the controller and no such agent exists.

Install and put these tools on the node that will execute the build's `PATH`:

- Java 21
- Go 1.24.4 or later
- Node.js 20 and Yarn Classic 1.22
- AWS CLI v2
- Docker Engine/CLI with a running daemon
- Helm 3
- Python 3 and Git

The pipeline's Go tests and checkout integration tests use Docker/Testcontainers.
The Jenkins build account must be able to reach the Docker daemon. Membership
in the `docker` group grants effectively root-level access; restrict access to
trusted build jobs and users. Running Docker-enabled builds on the controller
increases the impact of compromised or untrusted jobs, so limit who can start
them and prefer a separate agent.

Check the toolchain and AWS role from the same node/account Jenkins will use
(the controller, if that is where you chose to run builds):

```bash
java -version
go version
node --version
yarn --version
aws --version
docker version
helm version
python3 --version
git --version
aws sts get-caller-identity
```

The last command must succeed using the attached role, without prompting for
keys. Confirm Docker can build and run containers as the same OS account that
will run the Jenkins agent.

## 7. Install and initialize Jenkins

1. Install a supported Jenkins LTS controller on a separate Linux host using
   the official Jenkins package instructions for that host's distribution.
   Install Java 21 on the controller.
2. Restrict access to the Jenkins web UI to administrators and trusted users.
   Terminate HTTPS at a trusted reverse proxy or load balancer; do not expose
   an unprotected Jenkins port to the public internet.
3. Complete the initial setup wizard and create an administrator account.
4. Install/update these plugins from **Manage Jenkins → Plugins**:
   - Pipeline
   - Git
   - GitHub Branch Source
   - SSH Agent
   - JUnit
5. Create a permanent inbound agent/node in **Manage Jenkins → Nodes**:
   - Name: for example `retail-linux-docker`
   - Labels: `linux-docker`
   - Launch method: inbound agent (WebSocket is suitable when SSH ingress is
     not desired)
   - Remote root directory: a writable dedicated directory, for example
     `/var/lib/jenkins-agent`
6. Start the agent process on the agent host using the connection URL, secret,
   and agent name shown on its Jenkins node page. Run it under a dedicated
   account and configure it as a supervised service so it reconnects after
   reboot.
7. Confirm the node is online and shows the `linux-docker` label before
   creating the pipeline job.

Do not run untrusted pull-request builds on an agent that has the AWS role,
Docker access, or GitHub write credentials.

## 8. Add the GitHub SSH credential

The deploy credential is used by the pipeline to push the chart-values commit.
Create a dedicated SSH key (or use an approved machine-user key), add its
public key to GitHub with write permission to the selected repository, and
store the private key in Jenkins:

1. Go to **Manage Jenkins → Credentials** (or the appropriate folder scope).
2. Add **SSH Username with private key**.
3. Set the credential ID to exactly `gitops-ssh-key`.
4. Enter the GitHub SSH username, usually `git`.
5. Add the private key and restrict its scope to this job/folder.
6. Ensure the agent trusts GitHub's SSH host key using your organization's
   approved host-key verification strategy.

If the GitHub repository is private, also configure a read credential for
multibranch SCM discovery and checkout. It can be the same credential if your
organization permits it. Verify it has write access to `main` for the pipeline
push.

## 9. Create the multibranch pipeline job and webhook

1. In Jenkins, choose **New Item → Multibranch Pipeline**.
2. Under **Branch Sources**, add **GitHub** and select the repository owner and
   repository. Configure the read credential if required.
3. In **Build Configuration**, use **by Jenkinsfile** and set the script path
   to `Jenkinsfile`.
4. Save the job and run **Scan Multibranch Pipeline Now**. Jenkins should find
   the `main` branch and any other eligible branches.
5. In the GitHub repository settings, add a webhook pointing to the Jenkins
   GitHub webhook endpoint (commonly `https://JENKINS_HOST/github-webhook/`).
   Enable push events and use HTTPS.
6. Send a test event and confirm GitHub reports a successful delivery and
   Jenkins starts the corresponding branch build.

Use the exact repository configured in step 2. On a successful SCM checkout,
the pipeline expects an `origin` remote that it can switch to SSH for the
GitOps push.

## 10. Set Jenkins environment variables

Set these variables in a Jenkins folder or the multibranch job's trusted
environment configuration:

| Variable | Required value |
| --- | --- |
| `AWS_ACCOUNT_ID` | The 12-digit AWS account ID containing the ECR repositories |
| `AWS_REGION` | The AWS region containing ECR and the EKS deployment |

Do not store AWS keys here. The pipeline validates both values and uses the
agent's attached IAM role for AWS authentication. Do not set credentials in
the Jenkinsfile.

## 11. Run and verify the first build

Trigger a build of `main`. The first build for the job publishes images even
if Jenkins does not report a source changeset. Watch for these stages:

- **Checkout** succeeds and checks out the intended `main`.
- **Lint Helm charts** succeeds.
- **Test services** completes all parallel service branches.
- **Build, publish, and deploy** authenticates to AWS, publishes or reuses
  images, updates chart values, and pushes the GitOps commit.

After the build:

1. In ECR, confirm all five repositories contain an image tagged with the
   version in `src/app/chart/Chart.yaml`.
2. In GitHub, confirm a `ci: deploy images ... [skip ci]` commit updated the
   five service chart values on `main`.
3. In Argo CD, confirm all five applications are synced and healthy.
4. In Kubernetes, check pods and events in the `retail-store` namespace:

   ```bash
   kubectl get applications -n argocd
   kubectl get pods -n retail-store
   kubectl get events -n retail-store --sort-by=.lastTimestamp
   ```

5. Before a subsequent release, bump `src/app/chart/Chart.yaml` and confirm
   Jenkins builds a new SemVer-tagged image and Argo CD rolls out the updated
   chart values.

The pipeline uses immutable ECR tags and labels each image with its source Git
revision. If the same release build is retried, Jenkins reuses an existing
image only when its revision matches the current source. If the version already
belongs to different code, the build fails and asks you to bump the chart
version.

## 12. Troubleshooting

| Symptom | Check |
| --- | --- |
| Jenkins cannot find the `linux-docker` agent | Confirm the agent is online and has that exact label. |
| Docker/Testcontainers tests fail | Check that Docker is running and the Jenkins agent account can use the Docker daemon. |
| `aws sts get-caller-identity` fails | Confirm the instance role is attached to the agent and its trust relationship is correct; do not add static keys as a workaround. |
| ECR login or image push is denied | Check `AWS_ACCOUNT_ID`, `AWS_REGION`, repository names, and the scoped ECR push policy. |
| ECR repository is missing | Create the exact `retail-store-{ui,catalog,cart,checkout,orders}` repositories in the configured account and region. |
| Jenkins cannot push the chart update | The pipeline fetches and rebases its generated commit, then retries pushes up to three times. Confirm `gitops-ssh-key` can write to `main`; if Jenkins reports a rebase conflict, reconcile the chart-value changes and rerun the build. |
| Argo CD reports a repository/project error | Compare the `repoURL` in all five application files with the `sourceRepos` allowed in the AppProject and the real repository URL. |
| Argo CD cannot pull a private image | Confirm the EKS node role has ECR pull permissions and resolve the charts' `regcred` reference as described in step 5. |
| A branch build does not publish images | Publishing is intentionally restricted to `main` and to service changes under `src/`, except for a job's first build. |
| A chart-only commit starts another build | Tests may run, but the publish stage is gated on `src/**` changes and should be skipped. |
| ECR reports a SemVer tag conflict | Keep ECR tags immutable. Retry the same release commit to reuse matching images, or bump `src/app/chart/Chart.yaml` before publishing different code. |

## 13. Operational notes and cleanup

- Treat Jenkins controller and agent access as privileged. Keep Jenkins,
  plugins, agent OS packages, and credentials maintained and access-controlled.
- Keep GitHub write credentials off untrusted branches and pull-request jobs.
- Restrict the AWS role to only the required repositories and operations.
- Keep Argo CD pointed at the same repository and branch Jenkins updates.
- Terraform creates billable cloud resources. To remove the test environment,
  first review the Terraform state and the impact on workloads/data, then run
  `terraform destroy` from the configured Terraform directory and AWS profile.
