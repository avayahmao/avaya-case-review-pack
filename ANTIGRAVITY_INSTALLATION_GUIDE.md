# Antigravity App Installation and Login Guide

> [!NOTE]
> 🌐 **HTML Version Available**: If you do not have a Markdown reader, open **[ANTIGRAVITY_INSTALLATION_GUIDE.html](file:///e:/case/avaya-case-review-pack/ANTIGRAVITY_INSTALLATION_GUIDE.html)** directly in your web browser.
>
> Source: [Avaya Confluence Wiki — Antigravity Installation and Login Guide](https://avaya.atlassian.net/wiki/spaces/DLBBEWIKI/pages/2476572765/Antigravity+CLI+Installation+and+Login+Guide)

This guide walks you through installing the **Antigravity App** and signing in using Google OAuth with the dedicated corporate Google Cloud Project ID: **`geminienterpriseprod`**.

---

## 1. Installation Commands

Select the command corresponding to your operating system and shell environment:

| Operating System | Terminal / Shell | Installation Command |
|---|---|---|
| **macOS** | Terminal | `curl -fsSL https://antigravity.google/cli/install.sh \| bash` |
| **Linux** | Terminal | `curl -fsSL https://antigravity.google/cli/install.sh \| bash` |
| **Windows** | **PowerShell** *(Recommended)* | `irm https://antigravity.google/cli/install.ps1 \| iex` |
| **Windows** | Command Prompt (CMD) | `curl -fsSL https://antigravity.google/cli/install.cmd -o install.cmd && install.cmd && del install.cmd` |

> [!TIP]
> On Windows, **PowerShell** is the simplest and recommended option.

---

## 2. Step-by-Step Login Procedure

1. **Launch Antigravity**: Open the **Antigravity App** after installation completes.
2. **Start Sign-In**: When prompted to sign in or choose an authentication method.
3. **Select Login Method**: Choose **Option 2: Use a Google Cloud Project**.
4. **Authenticate**: Complete the Google OAuth browser login using your corporate **Avaya email** (`@avaya.com`).
5. **Enter Project ID**: After browser authentication completes, enter the project ID exactly as:
   ```text
   geminienterpriseprod
   ```

---

## 3. Quick Reference

| Step | What to Enter / Select |
|---|---|
| **Application** | **Antigravity App** |
| **Login Method** | Google OAuth |
| **Project Selection** | **Option 2: Use a Google Cloud Project** |
| **Account** | Your Avaya e-mail (`@avaya.com`) |
| **Project ID** | `geminienterpriseprod` |

---

## 4. Validation Checklist

- [ ] Antigravity App installation command completed successfully.
- [ ] Antigravity App launches successfully on your workstation.
- [ ] Google OAuth login completed successfully using your `@avaya.com` email.
- [ ] Project ID `geminienterpriseprod` entered and accepted.

---

## 5. Troubleshooting & FAQs

### Q1: Antigravity App fails to launch or command not found.
- **Fix**: Restart your computer or reopen your terminal so system environment variables and shortcuts update.

### Q2: Authentication failed or wrong project permissions.
- **Fix**: Ensure you selected **Option 2: Use a Google Cloud Project** during login, and verify you signed in with your `@avaya.com` account rather than a personal Google account.

### Q3: Project ID error.
- **Fix**: Double check that the project ID is typed or pasted exactly as `geminienterpriseprod` (no extra spaces or quotes).
