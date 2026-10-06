# Bounded Class-B model branch task

This unit gives `B_REVERSIBLE_BRANCH` one fixed documentation contract:
classify whether the earlier Class-B fixed-document pilot has run, then
update the stale status in `docs/engineering/CLASS_B_ISOLATION.md`. The
model returns a status code; fixed policy constructs the exact document
change. The model cannot choose a path, shell command, Git ref, PR base or
replacement prose. A separate verifier checks all output bytes and the
raw model decision independently.

The proposal job has `contents: read` and checks out without persisted
credentials. A pinned, Apache-2.0 Qwen2.5-Coder-1.5B GGUF and pinned
`llama.cpp` CPU release are downloaded and checked by SHA-256. The model
files are the [Qwen Q4_K_M GGUF](https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF/blob/main/qwen2.5-coder-1.5b-instruct-q4_k_m.gguf)
and [llama.cpp b11429 Ubuntu x64 release](https://github.com/ggml-org/llama.cpp/releases/tag/b11429).
The model
runs as a non-root user in a read-only container with no network route,
Docker socket, repository mount or Git token. Only two public documents,
the pinned runtime/model, a worker script and a 1 MB output tmpfs are
mounted. CPU, memory, process count, shared memory and wall time are bounded.
The worker exercises denied path, command and network attempts and records
the refusal events. The model output and receipt are untrusted data.

Only a successful `workflow_dispatch` on `main` can run the separate
publisher job with `contents: write` and `pull-requests: write`. That job
checks out trusted default-branch code, downloads the three verified output
files, re-verifies the exact document diff, and pushes a branch named solely
from the numeric workflow run ID. It opens a draft PR for human review.
There is no merge, deploy, production state write or self-approval path.
The public repository's current main ruleset still allows some direct
fast-forward pushes, so the coordinator token has more theoretical Git
authority than the worker contract. The token is never passed to the model
container or proposal job. Broader Class-B contracts remain inactive.

GitHub-created PRs made with `GITHUB_TOKEN` may not trigger ordinary PR
workflows; the proposal job's model, policy and verifier results are the
initial CI evidence. A reviewer can require an explicit validation run
before merge. This task is not proof that arbitrary model-written code is
safe or useful. The small model may fail the status classification; that
leaves no candidate branch and fails the workflow.
