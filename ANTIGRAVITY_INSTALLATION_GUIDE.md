# Antigravity App Installation and Login Guide

> [!NOTE]
> 🌐 **HTML Version Available**: If you do not have a Markdown reader, open **[ANTIGRAVITY_INSTALLATION_GUIDE.html](file:///e:/case/avaya-case-review-pack/ANTIGRAVITY_INSTALLATION_GUIDE.html)** directly in your web browser.
>
> Source: [Avaya Confluence Wiki — Antigravity Installation and Login Guide](https://avaya.atlassian.net/wiki/spaces/DLBBEWIKI/pages/2476572765/Antigravity+CLI+Installation+and+Login+Guide)

This guide walks you through installing the **Antigravity Desktop App** and signing in using Google OAuth with the dedicated corporate Google Cloud Project ID: **`geminienterpriseprod`**.

---

## 1. Installing the Antigravity App

Download and run the installer for your operating system:

| Operating System | Installer Format | Installation Steps |
|---|---|---|
| **Windows** | `.exe` / `.msi` Installer | Download the Windows installer (`Antigravity Setup.exe`) and double-click to launch the setup wizard. Follow the on-screen prompts to complete installation. |
| **macOS** | `.dmg` Package | Download the macOS disk image (`Antigravity.dmg`), open it, and drag the **Antigravity** icon into your `Applications` folder. |
| **Linux** | `.deb` / `.rpm` / `.AppImage` | Download the appropriate package for your distribution and install via your system package manager or run the AppImage. |

---

## 2. Step-by-Step Login Procedure

1. **Launch App**: Open the **Antigravity App** from your Start Menu, Applications folder, or desktop shortcut.
2. **Start Sign-In**: Click **Sign In** on the welcome screen.
3. **Select Login Method**: When prompted to choose an authentication method, select **Option 2: Use a Google Cloud Project**.
4. **Authenticate**: In the Google OAuth browser window that opens, sign in using your corporate **Avaya email** (`@avaya.com`).
5. **Enter Project ID**: After browser authentication completes, enter the project ID exactly as:
   ```text
   geminienterpriseprod
   ```

---

## 3. Quick Reference

| Step | What to Enter / Select |
|---|---|
| **Application** | **Antigravity Desktop App** |
| **Login Method** | Google OAuth |
| **Project Selection** | **Option 2: Use a Google Cloud Project** |
| **Account** | Your Avaya e-mail (`@avaya.com`) |
| **Project ID** | `geminienterpriseprod` |

---

## 4. Validation Checklist

- [ ] Antigravity App installed and launches successfully on your workstation.
- [ ] Google OAuth login completed successfully in your browser using your `@avaya.com` email.
- [ ] Project ID `geminienterpriseprod` entered and accepted.
- [ ] Antigravity App main interface is active and connected.

---

## 5. Troubleshooting & FAQs

### Q1: Antigravity App fails to launch or closes immediately.
- **Fix**: Verify your workstation meets system requirements, and ensure antivirus/corporate security policies allow running Antigravity.

### Q2: Authentication error or wrong account selected during login.
- **Fix**: Ensure you selected **Option 2: Use a Google Cloud Project** during login, and verify you signed in with your `@avaya.com` email rather than a personal Google account.

### Q3: Project ID error.
- **Fix**: Double check that the project ID is typed or pasted exactly as `geminienterpriseprod` (no extra spaces or quotes).
