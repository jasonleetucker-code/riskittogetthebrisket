pipeline {
  agent any

  options {
    timestamps()
    disableConcurrentBuilds()
  }

  environment {
    PYTHONUNBUFFERED = '1'
  }

  stages {
    stage('Checkout') {
      steps {
        checkout scm
      }
    }

    stage('Git Info') {
      steps {
        script {
          env.GIT_COMMIT_SHORT = isUnix()
            ? sh(returnStdout: true, script: 'git rev-parse --short HEAD').trim()
            : bat(returnStdout: true, script: '@echo off\r\ngit rev-parse --short HEAD').trim()
        }
        echo "Branch: ${env.BRANCH_NAME ?: 'main'} | Commit: ${env.GIT_COMMIT_SHORT}"
      }
    }

    stage('Validate') {
      when {
        expression { fileExists('scripts/validate_ingest.py') }
      }
      steps {
        script {
          if (isUnix()) {
            sh 'python scripts/validate_ingest.py --repo .'
          } else {
            bat 'python scripts\\validate_ingest.py --repo .'
          }
        }
      }
    }

    stage('Identity Resolve') {
      when {
        expression { fileExists('scripts/identity_resolve.py') }
      }
      steps {
        script {
          if (isUnix()) {
            sh 'python scripts/identity_resolve.py --repo .'
          } else {
            bat 'python scripts\\identity_resolve.py --repo .'
          }
        }
      }
    }

    stage('Backend Smoke') {
      steps {
        script {
          if (isUnix()) {
            sh 'python --version'
            sh '''python - <<'PY'
import py_compile
py_compile.compile("server.py", doraise=True)
py_compile.compile("Dynasty Scraper.py", doraise=True)
print("Python compile checks passed")
PY'''
          } else {
            bat 'python --version'
            bat 'python -c "import py_compile; py_compile.compile(r\'server.py\', doraise=True); py_compile.compile(r\'Dynasty Scraper.py\', doraise=True); print(\'Python compile checks passed\')"'
          }
        }
      }
    }

    stage('API Contract Check') {
      when {
        expression { fileExists('scripts/validate_api_contract.py') }
      }
      steps {
        script {
          if (isUnix()) {
            sh 'python scripts/validate_api_contract.py --repo .'
          } else {
            bat 'python scripts\\validate_api_contract.py --repo .'
          }
        }
      }
    }

    stage('Frontend Build') {
      when {
        expression { fileExists('frontend/package.json') }
      }
      steps {
        dir('frontend') {
          script {
            if (isUnix()) {
              sh 'npm ci'
              sh 'npm run build'
            } else {
              bat 'npm ci'
              bat 'npm run build'
            }
          }
        }
      }
    }

    stage('Regression Harness') {
      when {
        expression { fileExists('package.json') && fileExists('tests/e2e/playwright.config.js') }
      }
      steps {
        script {
          if (isUnix()) {
            sh 'npm ci'
            sh 'npx playwright install chromium'
            sh 'npm run regression'
          } else {
            bat 'npm ci'
            bat 'npx playwright install chromium'
            bat 'npm run regression'
          }
        }
      }
    }
  }

  post {
    always {
      script {
        def stamp = new Date().format("yyyy-MM-dd'T'HH:mm:ssXXX")
        def info = [
          buildNumber: env.BUILD_NUMBER,
          branch: env.BRANCH_NAME ?: 'main',
          commit: env.GIT_COMMIT ?: '',
          shortCommit: env.GIT_COMMIT_SHORT ?: '',
          timestamp: stamp,
          result: currentBuild.currentResult
        ]
        def json = groovy.json.JsonOutput.prettyPrint(groovy.json.JsonOutput.toJson(info))
        writeFile file: 'data/build_info.json', text: json
      }
      archiveArtifacts artifacts: 'data/build_info.json', allowEmptyArchive: true
    }
  }
}
