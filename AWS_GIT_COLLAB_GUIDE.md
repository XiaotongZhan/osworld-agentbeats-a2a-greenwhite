---
title: AWS Git Collaboration Guide
author: Sean Zhan
date: 2025-10-30
---

# 1. Prepare Your Working Directory

Create your own workspace folder, for example:

```bash
mkdir -p ~/zxt && cd ~/zxt
````

# 2. Generate a Personal SSH Key (One per Person)

Use your own name or ID in the filename, such as `id_ed25519_zxt`:

```bash
ssh-keygen -t ed25519 -C "your_github_email@example.com" -f ~/.ssh/id_ed25519_zxt -N ""
```

Start the SSH agent and add the key:

```bash
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519_zxt
chmod 700 ~/.ssh
chmod 600 ~/.ssh/id_ed25519_zxt ~/.ssh/id_ed25519_zxt.pub
```

# 3. Configure SSH Alias (So Git Knows Which Key to Use)

Open or create the SSH configuration file:

```bash
nano ~/.ssh/config
```

Add the following lines at the end:

```bash
# === GitHub SSH Config for zxt ===
Host github-zxt
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519_zxt
    IdentitiesOnly yes
```

Save and exit:

* Press `Ctrl + O` → Enter to save
* Press `Ctrl + X` → Exit the editor

Then set the correct permissions:

```bash
chmod 600 ~/.ssh/config
```

# 4. Add Your Public Key to GitHub

Display your public key:

```bash
cat ~/.ssh/id_ed25519_zxt.pub
```

Copy the entire line and add it to GitHub:

**GitHub → Settings → SSH and GPG keys → New SSH key**

* **Title:** `aws-zxt`
* **Key:** paste the copied content
* Click **Add SSH key**

Verify that your key works:

```bash
ssh -T git@github-zxt
```

Expected success message:

```bash
Hi <your_github_username>! You've successfully authenticated, but GitHub does not provide shell access.
```

# 5. Clone the Repository (Using Your Alias)

```bash
cd ~/zxt
git clone git@github-zxt:XiaotongZhan/cs294-ai-agent.git
cd cs294-ai-agent
```

# 6. Set Local Git Identity (Affects This Repository Only)

```bash
git config user.name  "Zhan Xiaotong"
git config user.email "your_email@example.com"
```

Verify your settings:

```bash
git config --list
```