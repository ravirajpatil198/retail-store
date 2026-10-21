# Jenkins CI/CD

This pipeline checks the five services, builds their Docker images, publishes
SemVer-tagged images to Amazon ECR, and updates the Helm values watched by
Argo CD. Argo CD performs the Kubernetes rollout after it sees the values
commit on `main`; Jenkins does not need cluster-admin credentials.

## Jenkins setup

1. Create a **Multibranch Pipeline** for the GitHub repository with a webhook
   trigger. The repository's Argo CD applications currently watch the `main`
   branch.
2. The Jenkinsfile uses `agent any`, so the build runs on any available
   executor, including the built-in controller node if it has executors
   enabled. The selected node must be Linux, have a working Docker daemon, and
   have these tools on `PATH`:
   - Java 21
   - Go 1.24.4 or later
   - Node.js 20 and Yarn Classic 1.22
   - AWS CLI v2, Helm 3, Python 3, and Git
   The Go catalog tests and checkout integration tests use Testcontainers, so
   the build node must allow builds to access its Docker daemon. For production,
   use a dedicated Linux agent instead of running builds on the controller;
   set the Jenkinsfile agent to `label 'linux-docker'` and configure that label
   on the dedicated agent.
3. Install Jenkins Pipeline, Git, SSH Agent, and JUnit plugins.
4. Set `AWS_ACCOUNT_ID` and `AWS_REGION` in the Jenkins folder or build-node
   environment. Attach an AWS IAM role to the build node rather than storing
   AWS access keys in the repository or Jenkinsfile.
5. Create these ECR repositories in that account and region:
   `retail-store-ui`, `retail-store-catalog`, `retail-store-cart`,
   `retail-store-checkout`, and `retail-store-orders`. Configure tag
   mutability as **Immutable**. The agent's IAM role needs
   `ecr:GetAuthorizationToken` plus `ecr:DescribeImages` and ECR image upload
   permissions (`ecr:BatchCheckLayerAvailability`,
   `ecr:InitiateLayerUpload`, `ecr:UploadLayerPart`,
   `ecr:CompleteLayerUpload`, and `ecr:PutImage`) for those repositories.
6. Add a Jenkins SSH private-key credential with the ID
   `gitops-ssh-key`. Its GitHub deploy key or machine-user key must be allowed
   to push to `main`. Ensure the checkout's `origin` is the same GitHub
   repository that Argo CD tracks and that the Jenkins agent trusts GitHub's
   SSH host key.
7. Ensure the EKS worker role can pull from those ECR repositories, or
   configure the Kubernetes image-pull secret referenced by the service Helm
   charts.

## Pipeline behavior

- Every branch runs Helm lint, Go tests, Maven tests, and checkout lint/build
  and integration tests.
- Only `main` publishes images. The image tag comes from
  `src/app/chart/Chart.yaml` (`MAJOR.MINOR.PATCH`) and the service chart values
  are updated to those immutable ECR tags. Bump that version for each new
  release. Images include their source Git revision as an OCI label; a retry
  reuses an existing tag only when it belongs to the same revision, and fails
  with a version-bump message if the tag belongs to different code.
- Jenkins pushes the chart-values commit to `main`. The resulting
  chart-only build does not publish images again, avoiding a push loop.
- The first `main` build publishes all five images. Later builds publish when
  files under `src/` change, except for the five generated service chart
  `values.yaml` files.
- Repository URLs, AWS account, region, and the GitOps branch are not
  credentials: review them when adapting this pipeline to another account or
  branch. If Argo CD watches a different branch, update both the pipeline's
  publish condition/push ref and the Argo CD application `targetRevision`.
