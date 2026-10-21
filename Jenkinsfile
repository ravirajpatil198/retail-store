pipeline {
  agent {
    agent any
  }

  options {
    buildDiscarder(logRotator(numToKeepStr: '20'))
    disableConcurrentBuilds()
    skipDefaultCheckout(true)
    timestamps()
  }

  stages {
    stage('Checkout') {
      steps {
        checkout scm
      }
    }

    stage('Lint Helm charts') {
      steps {
        sh 'helm lint src/cart/chart src/catalog/chart src/checkout/chart src/orders/chart src/ui/chart'
      }
    }

    stage('Test services') {
      parallel {
        stage('Catalog (Go)') {
          steps {
            dir('src/catalog') {
              sh 'go test ./...'
            }
          }
        }

        stage('Cart (Java)') {
          steps {
            dir('src/cart') {
              sh 'AWS_ACCESS_KEY_ID=dummy AWS_SECRET_ACCESS_KEY=dummy ./mvnw --batch-mode --no-transfer-progress test -DexcludedGroups=integration'
            }
          }
        }

        stage('Orders (Java)') {
          steps {
            dir('src/orders') {
              sh './mvnw --batch-mode --no-transfer-progress test -DexcludedGroups=integration'
            }
          }
        }

        stage('UI (Java)') {
          steps {
            dir('src/ui') {
              sh './mvnw --batch-mode --no-transfer-progress test -DexcludedGroups=integration'
            }
          }
        }

        stage('Checkout (Node.js)') {
          steps {
            dir('src/checkout') {
              sh 'yarn install --frozen-lockfile --non-interactive'
              sh 'yarn lint'
              sh 'yarn build'
              sh 'yarn test:integration --runInBand'
            }
          }
        }
      }
    }

    stage('Build, publish, and deploy') {
      when {
        branch 'main'
        anyOf {
          changeset 'src/**'
          expression { currentBuild.previousBuild == null }
        }
      }
      steps {
        script {
          if (!(env.AWS_ACCOUNT_ID ==~ /^\d{12}$/)) {
            error('Set AWS_ACCOUNT_ID to the 12-digit AWS account ID in Jenkins.')
          }
          if (!(env.AWS_REGION ==~ /^[a-z0-9-]+$/)) {
            error('Set AWS_REGION in Jenkins, for example us-west-2.')
          }

          env.ECR_REGISTRY = "${env.AWS_ACCOUNT_ID}.dkr.ecr.${env.AWS_REGION}.amazonaws.com"
          env.IMAGE_TAG = sh(script: 'git rev-parse --short=12 HEAD', returnStdout: true).trim()
        }

        sh '''
          set -eu
          aws sts get-caller-identity >/dev/null
          aws ecr get-login-password --region "$AWS_REGION" |
            docker login --username AWS --password-stdin "$ECR_REGISTRY"

          for service in ui catalog cart checkout orders; do
            image="$ECR_REGISTRY/retail-store-$service:$IMAGE_TAG"
            if aws ecr describe-images --region "$AWS_REGION" \
              --repository-name "retail-store-$service" \
              --image-ids "imageTag=$IMAGE_TAG" >/dev/null 2>&1; then
              echo "Reusing existing image $image"
              continue
            fi
            docker build --pull --tag "$image" "src/$service"
            docker push "$image"
          done
        '''

        sh '''
          python3 scripts/update-ecr-image-tags.py "$ECR_REGISTRY" "$IMAGE_TAG"
          git config user.name "Jenkins"
          git config user.email "jenkins@localhost"
          git add src/ui/chart/values.yaml src/catalog/chart/values.yaml \
            src/cart/chart/values.yaml src/checkout/chart/values.yaml \
            src/orders/chart/values.yaml
          if ! git diff --cached --quiet; then
            git commit -m "ci: deploy images $IMAGE_TAG [skip ci]"
          fi
        '''

        script {
          def originUrl = sh(script: 'git remote get-url origin', returnStdout: true).trim()
          def pushUrl = originUrl.replaceFirst(/^https:\/\/github\.com\//, 'git@github.com:')
          if (!pushUrl.startsWith('git@github.com:')) {
            error('The origin remote must be a GitHub HTTPS or SSH URL to push the GitOps update.')
          }

          withEnv(["GITOPS_SSH_URL=${pushUrl}"]) {
            sshagent(credentials: ['gitops-ssh-key']) {
              sh '''
                git remote set-url origin "$GITOPS_SSH_URL"
                git push origin HEAD:refs/heads/main
              '''
            }
          }
        }
      }
      post {
        always {
          sh 'if [ -n "$ECR_REGISTRY" ]; then docker logout "$ECR_REGISTRY" >/dev/null 2>&1 || true; fi'
        }
      }
    }
  }

  post {
    always {
      junit allowEmptyResults: true, testResults: 'src/**/target/surefire-reports/*.xml'
    }
  }
}
