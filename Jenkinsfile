pipeline {
  agent any

  options {
    buildDiscarder(logRotator(numToKeepStr: '5'))
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
        sh 'helm dependency build src/app/chart'
        sh 'helm lint src/app/chart src/cart/chart src/catalog/chart src/checkout/chart src/orders/chart src/ui/chart'
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

    stage('Build and publish images') {
      when {
        allOf {
          anyOf {
            branch 'main'
            branch 'feature'
            buildingTag()
          }
          anyOf {
            allOf {
              changeset 'src/**'
              not {
                anyOf {
                  changeset 'src/ui/chart/values.yaml'
                  changeset 'src/catalog/chart/values.yaml'
                  changeset 'src/cart/chart/values.yaml'
                  changeset 'src/checkout/chart/values.yaml'
                  changeset 'src/orders/chart/values.yaml'
                }
              }
            }
            expression { currentBuild.previousBuild == null }
            buildingTag()
          }
        }
      }
      steps {
        script {
          if (!(env.AWS_ACCOUNT_ID ==~ /^\d{12}$/)) {
            error('Set AWS_ACCOUNT_ID to the 12-digit AWS account ID in Jenkins.')
          }
          if (!(env.AWS_REGION ==~ /^[a-z0-9-]+$/)) {
            error('Set AWS_REGION in Jenkins, for example ap-south-1.')
          }

          env.ECR_REGISTRY = "${env.AWS_ACCOUNT_ID}.dkr.ecr.${env.AWS_REGION}.amazonaws.com"
          env.GIT_REVISION = sh(script: 'git rev-parse HEAD', returnStdout: true).trim()
          env.IMAGE_TAG = env.GIT_REVISION.take(12)
          env.VERSION_TAG = ''

          if (env.TAG_NAME) {
            if (!(env.TAG_NAME ==~ /^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-((?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$/)) {
              error("Git tag '${env.TAG_NAME}' is not a valid semantic version (expected vMAJOR.MINOR.PATCH, optionally with prerelease/build metadata).")
            }
            env.VERSION_TAG = env.TAG_NAME.replaceFirst(/^v/, '').replace('+', '_')
          }
        }

        sh '''
          set -eu
          VERSION_TAG="${VERSION_TAG:-}"
          aws sts get-caller-identity >/dev/null
          aws ecr get-login-password --region "$AWS_REGION" |
            docker login --username AWS --password-stdin "$ECR_REGISTRY"

          for service in ui catalog cart checkout orders; do
            image="$ECR_REGISTRY/retail-store-$service:$IMAGE_TAG"
            if aws ecr describe-images --region "$AWS_REGION" \
              --repository-name "retail-store-$service" \
              --image-ids "imageTag=$IMAGE_TAG" >/dev/null 2>&1; then
              docker pull "$image"
              existing_revision=$(docker image inspect \
                --format='{{ with .Config.Labels }}{{ index . "org.opencontainers.image.revision" }}{{ end }}' "$image")
              if [ "$existing_revision" != "$GIT_REVISION" ]; then
                echo "Image tag $image already belongs to revision ${existing_revision:-unknown}."
                echo "Refusing to reuse an image from different source code."
                exit 1
              fi
              echo "Reusing existing image $image"
            else
              docker build --pull \
                --label "org.opencontainers.image.revision=$GIT_REVISION" \
                --tag "$image" "src/$service"
              docker push "$image"
            fi

            if [ -n "$VERSION_TAG" ]; then
              version_image="$ECR_REGISTRY/retail-store-$service:$VERSION_TAG"
              if aws ecr describe-images --region "$AWS_REGION" \
                --repository-name "retail-store-$service" \
                --image-ids "imageTag=$VERSION_TAG" >/dev/null 2>&1; then
                docker pull "$version_image"
                version_revision=$(docker image inspect \
                  --format='{{ with .Config.Labels }}{{ index . "org.opencontainers.image.revision" }}{{ end }}' "$version_image")
                if [ "$version_revision" != "$GIT_REVISION" ]; then
                  echo "Semantic version tag $version_image already belongs to revision ${version_revision:-unknown}."
                  echo "Refusing to move an existing release tag."
                  exit 1
                fi
                echo "Reusing existing semantic version image $version_image"
              else
                docker tag "$image" "$version_image"
                docker push "$version_image"
              fi
            fi
          done
        '''
      }
      post {
        always {
          sh 'if [ -n "$ECR_REGISTRY" ]; then docker logout "$ECR_REGISTRY" >/dev/null 2>&1 || true; fi'
        }
      }
    }

    stage('Update GitOps values') {
      when {
        expression {
          env.BRANCH_NAME == 'main' && env.IMAGE_TAG != null
        }
      }
      steps {
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

        sshagent(['gitops-ssh-key']) {
          sh '''
            set -eu
            git remote set-url origin git@github.com:ravirajpatil198/retail-store.git

            if [ "$(git rev-parse HEAD)" = "$GIT_REVISION" ]; then
              echo "No image-tag changes to commit; skipping GitOps push."
              exit 0
            fi

            attempt=1
            while [ "$attempt" -le 3 ]; do
              git fetch origin +refs/heads/main:refs/remotes/origin/main
              if ! git -c core.editor=true rebase --onto origin/main HEAD^ HEAD; then
                echo "Could not rebase the generated image-tag commit onto main."
                echo "Resolve conflicting chart values and rerun the build."
                git rebase --abort || true
                exit 1
              fi

              if git push origin HEAD:refs/heads/main; then
                exit 0
              fi

              echo "Push attempt $attempt failed; refreshing main and retrying."
              attempt=$((attempt + 1))
            done

            echo "Could not push the GitOps commit after 3 attempts."
            exit 1
          '''
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
