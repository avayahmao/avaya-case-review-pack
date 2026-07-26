# Antigravity App Installation and Login Guide (Windows)

> [!NOTE]
> 🌐 **HTML Version Available**: If you do not have a Markdown reader, open **[ANTIGRAVITY_INSTALLATION_GUIDE.html](file:///e:/case/avaya-case-review-pack/ANTIGRAVITY_INSTALLATION_GUIDE.html)** directly in your web browser.
>
> Source: [Avaya Confluence Wiki — Antigravity Installation and Login Guide](https://avaya.atlassian.net/wiki/spaces/DLBBEWIKI/pages/2476572765/Antigravity+CLI+Installation+and+Login+Guide)

This guide walks Windows users through downloading, installing, and signing in to the **Antigravity App** using Google OAuth with the dedicated corporate Google Cloud Project ID: **`geminienterpriseprod`**.

---

## 1. Where to Download & How to Install (Windows)

### 📌 System Requirements
- **Operating System**: Windows 10 / Windows 11 (64-bit)
- **Shell / Terminal**: Windows PowerShell or Command Prompt

### 📥 Download & Installation Options

Choose one of the following methods to download and install Antigravity on Windows:

#### Method A: PowerShell Automated Setup (Recommended)
Open **PowerShell** as Administrator or regular user and run:
```powershell
irm https://antigravity.google/cli/install.ps1 | iex
```

#### Method B: Direct Download / Website
1. Visit the official download portal: **[https://antigravity.google/](https://antigravity.google/)**
2. Download the Windows Installer package (`.ps1` or `.exe`).
3. Run the installer and follow the setup wizard.

#### Method C: Command Prompt (CMD)
If using standard Command Prompt (CMD), run:
```cmd
curl -fsSL https://antigravity.google/cli/install.cmd -o install.cmd && install.cmd && del install.cmd
```

---

## 2. Step-by-Step Login Procedure

1. **Launch App**: Open the **Antigravity App** or open a fresh terminal window.
2. **Start Sign-In**: Initiate login (or run `agy` in your terminal).
3. **Select Login Method**: When prompted to choose an authentication method, select **Option 2: Use a Google Cloud Project**.
4. **Authenticate**: In the Google OAuth browser window that opens, sign in using your corporate **Avaya email** (`@avaya.com`).
5. **Enter Project ID**: After browser authentication completes, enter the project ID exactly as:
   ```text
   geminienterpriseprod
   ```

---

## 3. Quick Reference Table

| Step | Detail / What to Enter |
|---|---|
| **Target OS** | Windows 10 / Windows 11 (64-bit) |
| **Download URL** | [https://antigravity.google/](https://antigravity.google/) |
| **Quick Install (PowerShell)** | `irm https://antigravity.google/cli/install.ps1 \| iex` |
| **Login Method** | Google OAuth |
| **Project Selection Option** | **Option 2: Use a Google Cloud Project** |
| **Account** | Your Avaya e-mail (`@avaya.com`) |
| **Project ID** | `geminienterpriseprod` |

---

## 4. Recommended Validation Checklist

- [ ] Antigravity App installed and launches successfully on Windows.
- [ ] Google OAuth login completed in browser using your `@avaya.com` email.
- [ ] Project ID `geminienterpriseprod` entered and accepted.
- [ ] Antigravity is ready for use.

---

## 5. Troubleshooting & FAQs

### Q1: `command not found` or App shortcut missing after installation.
- **Fix**: Close and reopen PowerShell / Command Prompt or restart your system so Windows refreshes its system PATH environment variables.

### Q2: Authentication failed or wrong account selected during OAuth.
- **Fix**: Ensure you selected **Option 2: Use a Google Cloud Project** during login, and verify you signed in with your `@avaya.com` corporate email rather than a personal Google account.

### Q3: Project ID error.
- **Fix**: Double check that the project ID is typed or pasted exactly as `geminienterpriseprod` (no trailing spaces or quotes).
