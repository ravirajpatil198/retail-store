# Jenkins CI/CD

This pipeline checks the five services, builds their Docker images, publishes
images tagged with their 12-character source commit SHA to Amazon ECR, and
updates the Helm values watched by Argo CD. Argo CD performs the Kubernetes
rollout after it sees the values commit on `main`; Jenkins does not need
cluster-admin credentials.

## Jenkins setup

1. Create a **Multibranch Pipeline** for the GitHub repository with a webhook
   trigger and ensure branch discovery includes `main` and `feature`. The
   repository's Argo CD applications currently watch the `main` branch.
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
   `ecr:GetAuthorizationToken`, `ecr:DescribeImages`, ECR image-pull
   permissions (`ecr:BatchGetImage`, `ecr:GetDownloadUrlForLayer`), and image
   upload permissions (`ecr:BatchCheckLayerAvailability`,
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
- The `main` and `feature` branches publish images to the five ECR repositories
  using the first 12 characters of the source Git commit as the immutable
  image tag. Each image includes its full source revision as an OCI label.
- If an image tag already exists, Jenkins reuses it only if its label matches
  the full source revision; otherwise the build fails rather than using
  different code under that tag.
- Only `main` updates Helm values and pushes the GitOps commit. `feature` only
  publishes images. Jenkins-generated service `values.yaml` changes do not
  trigger another image publish.
- Jenkins pushes the chart-values commit to `main`. The resulting
  chart-only build does not publish images again, avoiding a push loop.
- Before pushing, Jenkins fetches the latest `main` and rebases only its
  generated chart-values commit onto it. It retries a rejected push up to
  three times and never force-pushes; conflicting chart-value changes fail
  visibly and must be reconciled before retrying.
- The first build for each branch publishes all five images. Later builds
  publish when files under `src/` change, except for the five generated
  service chart `values.yaml` files.
- Repository URLs, AWS account, region, and the GitOps branch are not
  credentials: review them when adapting this pipeline to another account or
  branch. If Argo CD watches a different branch, update both the pipeline's
  publish condition/push ref and the Argo CD application `targetRevision`.
