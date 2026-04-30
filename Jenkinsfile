pipeline {
    agent any

    parameters {
        string(name: 'APP_NAME', defaultValue: 'amsz-task-service')
        string(name: 'OPENSHIFT_API_URL', defaultValue: 'https://api.example.com:6443')
        string(name: 'OPENSHIFT_NAMESPACE', defaultValue: 'amsz-dev')
        string(name: 'IMAGE_REGISTRY', defaultValue: 'image-registry.openshift-image-registry.svc:5000')
        string(name: 'APP_ENV', defaultValue: 'dev')
        string(name: 'LOG_LEVEL', defaultValue: 'INFO')
        string(name: 'REPLICAS', defaultValue: '1')
        string(name: 'WORKER_QUEUE', defaultValue: 'default')
        string(name: 'WORKER_CONCURRENCY', defaultValue: '2')
    }

    environment {
        VENV_DIR = '.venv'
        IMAGE_TAG = "${env.BUILD_NUMBER}"
        IMAGE_REF = "${params.IMAGE_REGISTRY}/${params.OPENSHIFT_NAMESPACE}/${params.APP_NAME}:${env.BUILD_NUMBER}"
    }

    stages {
        stage('Install Dependencies') {
            steps {
                sh 'python3 -m venv ${VENV_DIR}'
                sh '${VENV_DIR}/bin/pip install -r requirements-dev.txt'
            }
        }

        stage('Unit Test') {
            steps {
                sh 'chmod +x ci/run_unittest.sh'
                sh './ci/run_unittest.sh'
            }
        }

        stage('Functional Test') {
            steps {
                sh 'chmod +x ci/run_functionaltest.sh'
                sh './ci/run_functionaltest.sh'
            }
        }

        stage('Build Image') {
            steps {
                withCredentials([
                    usernamePassword(
                        credentialsId: 'image-registry-creds',
                        usernameVariable: 'REGISTRY_USER',
                        passwordVariable: 'REGISTRY_PASSWORD'
                    )
                ]) {
                    sh 'echo "$REGISTRY_PASSWORD" | docker login ${IMAGE_REGISTRY} --username "$REGISTRY_USER" --password-stdin'
                    sh 'docker build -t ${IMAGE_REF} .'
                    sh 'docker push ${IMAGE_REF}'
                }
            }
        }

        stage('Deploy To OpenShift') {
            steps {
                withCredentials([
                    string(credentialsId: 'openshift-token', variable: 'OPENSHIFT_TOKEN'),
                    string(credentialsId: 'amsz-api-key', variable: 'DEPLOY_API_KEY'),
                    string(credentialsId: 'amsz-database-url', variable: 'DEPLOY_DATABASE_URL')
                ]) {
                    sh '''
                        oc login "${OPENSHIFT_API_URL}" --token="${OPENSHIFT_TOKEN}"
                        oc project "${OPENSHIFT_NAMESPACE}"
                        oc process -f openshift/template.yaml \
                          -p APP_NAME="${APP_NAME}" \
                          -p APP_ENV="${APP_ENV}" \
                          -p IMAGE="${IMAGE_REF}" \
                          -p LOG_LEVEL="${LOG_LEVEL}" \
                          -p REPLICAS="${REPLICAS}" \
                          -p WORKER_QUEUE="${WORKER_QUEUE}" \
                          -p WORKER_CONCURRENCY="${WORKER_CONCURRENCY}" \
                          -p API_KEY="${DEPLOY_API_KEY}" \
                          -p DATABASE_URL="${DEPLOY_DATABASE_URL}" \
                          | oc apply -f -
                    '''
                }
            }
        }
    }
}
