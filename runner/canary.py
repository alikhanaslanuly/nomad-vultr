from typing import Dict, List, Tuple

CANARY_IDS = ["aws_creds", "ssh_key", "npmrc", "gh_token", "dotenv", "kube"]


def get_marker(canary_id: str) -> str:
    return f"AIRLOCK-CANARY-{canary_id}"


def generate_canary_files(
    profile: str, home_dir: str, work_dir: str
) -> List[Tuple[str, str, str]]:

    files = []

    aws_content = f"""[default]
aws_access_key_id = AKIAIOSFODNN7EXAMPLE
aws_secret_access_key = {get_marker("aws_creds")}-secret-key-wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
region = us-east-1
"""
    files.append((".aws/credentials", aws_content, "aws_creds"))

    if profile != "ci":
        ssh_content = f"""-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZTAAAAAAAAAAAQAAABsAAAAIdXNy
QHRlc3QAAAAAE2VkaTI1NTE5AAAAICEXAMPLEKEYCANARYAAAAAAAAAAAAAAAAAAAAAAAA
AAAAECANARYKEYFAKEKEYFAKEKEYFAKEAAAA{get_marker("ssh_key")}
-----END OPENSSH PRIVATE KEY-----
"""
        files.append((".ssh/id_rsa", ssh_content, "ssh_key"))

    npmrc_content = f"""//registry.npmjs.org/:_authToken={get_marker("npmrc")}-token-9a8b7c6d5e4f3a2b1c
strict-ssl=true
"""
    files.append((".npmrc", npmrc_content, "npmrc"))

    gh_content = f"""github.com:
    user: octocat
    oauth_token: {get_marker("gh_token")}-oauth-abcdef1234567890
    git_protocol: https
"""
    files.append((".config/gh/hosts.yml", gh_content, "gh_token"))

    kube_content = f"""apiVersion: v1
clusters:
- cluster:
    server: https://10.96.0.1:443
  name: staging-cluster
contexts:
- context:
    cluster: staging-cluster
    user: developer
  name: staging
current-context: staging
kind: Config
users:
- name: developer
  user:
    token: {get_marker("kube")}-bearer-k8s-secret-token-xyz
"""
    files.append((".kube/config", kube_content, "kube"))

    dotenv_content = f"""DATABASE_URL=postgres://airlock_user:{get_marker("dotenv")}@db.internal:5432/production
API_SECRET_KEY=sec_{get_marker("dotenv")}_key
"""
    files.append(("work/.env", dotenv_content, "dotenv"))

    return files


def generate_profile_env(profile: str) -> Dict[str, str]:

    base_env = {
        "HOME": "/home/user",
        "USER": "user",
        "LOGNAME": "user",
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
    }

    if profile == "dev-laptop":
        base_env.update(
            {
                "AWS_ACCESS_KEY_ID": "AKIAIOSFODNN7EXAMPLE",
                "AWS_SECRET_ACCESS_KEY": f"{get_marker('aws_creds')}-env-secret",
                "AWS_DEFAULT_REGION": "us-east-1",
            }
        )

    elif profile == "ci":
        base_env.update(
            {
                "CI": "true",
                "CONTINUOUS_INTEGRATION": "true",
                "GITHUB_ACTIONS": "true",
                "GITHUB_WORKFLOW": "Build & Test",
                "GITHUB_RUN_ID": "123456789",
                "GITHUB_TOKEN": f"ghp_{get_marker('gh_token')}_ci_runner_token",
                "NPM_TOKEN": f"npm_{get_marker('npmrc')}_ci_deploy_token",
            }
        )

    elif profile == "future-date":
        base_env.update(
            {
                "AWS_ACCESS_KEY_ID": "AKIAIOSFODNN7EXAMPLE",
                "AWS_SECRET_ACCESS_KEY": f"{get_marker('aws_creds')}-env-secret",
                "FAKETIME": "+45d",
                "LD_PRELOAD": "/usr/lib/x86_64-linux-gnu/faketime/libfaketime.so.1",
                "DONT_FAKE_MONOTONIC": "1",
            }
        )

    return base_env


def get_profile_hostname(profile: str) -> str:
    if profile == "ci":
        return "runner-7f3a"
    return "alex-macbook"
