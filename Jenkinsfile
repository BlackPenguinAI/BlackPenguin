pipeline {
    agent any
    
    environment {
        // En un futuro podrías usar DOCR (DigitalOcean Container Registry)
        DOCKER_IMAGE = "blackpenguin/core-api" 
        DOCKER_TAG = "v1.${BUILD_NUMBER}"
        // Esta credencial se configura en el panel de Jenkins usando el k3s.yaml del paso 2
        KUBECONFIG = credentials('do-k3s-kubeconfig') 
    }
    
    stages {
        stage('Checkout Code') {
            steps {
                checkout scm
                echo '✅ Código descargado del repositorio'
            }
        }
        
        stage('Build Docker Image') {
            steps {
                echo '🏗️ Construyendo imagen del Backend (FastAPI)...'
                sh 'docker build -t ${DOCKER_IMAGE}:${DOCKER_TAG} .'
            }
        }
        
        stage('Deploy to DigitalOcean K3s') {
            steps {
                echo '🚢 Desplegando en clúster K3s (Zero-Downtime)...'
                // Actualización rodante de los pods en K3s
                sh 'kubectl set image deployment/bp-backend-deployment bp-backend=${DOCKER_IMAGE}:${DOCKER_TAG} --namespace=staging'
                
                // Esperar a que los nuevos contenedores estén listos antes de apagar los viejos
                sh 'kubectl rollout status deployment/bp-backend-deployment --namespace=staging'
            }
        }
    }
    
    post {
        success {
            echo '🎉 Despliegue en DigitalOcean exitoso.'
        }
        failure {
            echo '❌ Fallo en el pipeline. El entorno anterior sigue activo por seguridad.'
        }
    }
}