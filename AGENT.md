# Running Resume Tailor as a Managed Agent

This wraps the same tailoring logic as a hosted Anthropic Managed Agent. No local Streamlit / Python needed at runtime — Anthropic runs the agent in a sandboxed container; you just send messages and download the outputs.

## One-time setup

```sh
# Install the Anthropic CLI
brew install anthropics/tap/ant
xattr -d com.apple.quarantine "$(brew --prefix)/bin/ant"

# Auth
export ANTHROPIC_API_KEY="sk-ant-..."

# Create the agent + environment (save IDs)
AGENT_ID=$(ant beta:agents create < resume-tailor.agent.yaml --transform id -r)
ENV_ID=$(ant beta:environments create < resume-tailor.environment.yaml --transform id -r)

echo "AGENT_ID=$AGENT_ID" >  .agent.env
echo "ENV_ID=$ENV_ID"     >> .agent.env
```

## Each run: upload resume → start session → tail JD → download outputs

```sh
source .agent.env

# 1. Upload your resume — keep file_id
FILE_ID=$(ant beta:files upload --file ~/Documents/my_resume.pdf --purpose agent \
  --transform id -r)

# 2. Start a session with the resume mounted at /workspace/resume.pdf
SID=$(ant beta:sessions create \
  --agent "$AGENT_ID" \
  --environment-id "$ENV_ID" \
  --title "tailor for senior data engineer @ Acme" \
  --resource "{type: file, file_id: $FILE_ID, mount_path: /workspace/resume.pdf}" \
  --transform id -r)

echo "Watch in Console: https://platform.claude.com/workspaces/default/sessions/$SID"

# 3. Send the JD (paste text OR a LinkedIn URL)
ant beta:sessions:events send --session-id "$SID" <<'YAML'
events:
  - type: user.message
    content:
      - type: text
        text: |
          Tailor my resume (at /workspace/resume.pdf) for this job.
          JD URL: https://www.linkedin.com/jobs/view/4001234567
YAML

# 4. Stream until idle
ant beta:sessions:events stream --session-id "$SID"

# 5. Download outputs (the agent writes them to /mnt/session/outputs/)
mkdir -p ./out
for fid in $(ant beta:files list --scope-id "$SID" --transform id -r); do
  fname=$(ant beta:files retrieve-metadata --file-id "$fid" --transform filename -r)
  ant beta:files download --file-id "$fid" --output "./out/$fname"
done
ls -la ./out/
```

## Alternative: paste the JD text

Replace the `--message` send step with:

```sh
ant beta:sessions:events send --session-id "$SID" <<'YAML'
events:
  - type: user.message
    content:
      - type: text
        text: |
          Tailor my resume (at /workspace/resume.pdf) for the role below.
          JOB DESCRIPTION:
          <<paste the full JD here>>
YAML
```

## Updating the agent

After editing `resume-tailor.agent.yaml`:

```sh
source .agent.env
CURRENT_VERSION=$(ant beta:agents retrieve --agent-id "$AGENT_ID" --transform version -r)
ant beta:agents update --agent-id "$AGENT_ID" --version "$CURRENT_VERSION" \
  < resume-tailor.agent.yaml
```

Each update creates a new immutable version. New sessions get the latest by default; pin to a specific version with `--agent "{type: agent, id: $AGENT_ID, version: N}"` on session create.
