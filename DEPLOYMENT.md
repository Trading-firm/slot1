# 🚀 Trading Bot Deployment Guide: Google Cloud Platform (GCP) Windows VPS

This guide provides a comprehensive, step-by-step walkthrough to deploy your trading bot on a **Google Cloud Platform (GCP) Windows VPS**.

## ⚠️ Important Requirement
**You MUST use a Windows VPS.**
This bot relies on the **MetaTrader 5 (MT5)** desktop terminal, which only runs natively on Windows.
**Do NOT use Heroku, Render, or Linux servers.**

---

## ☁️ Phase 1: Create Your Google Cloud Windows Server

**Cost:** You get **$300 free credit** for 90 days.
**Note:** Windows Server uses credits faster than Linux. Monitor your billing, but the $300 should cover ~2-3 months easily.

### 1. Sign Up & Activate Account
1.  Go to [cloud.google.com/free](https://cloud.google.com/free) and click **"Start Free"**.
2.  Sign in with your Google Account.
3.  **IMPORTANT:** To use Windows Server, you must **"Activate"** your full account.
    - By default, you are in "Free Trial" mode which restricts Windows usage.
    - Click the **"Activate"** button at the top of the console.
    - *Don't worry:* This enables billing, but you will still use your **$300 free credit** first. You won't be charged until the credit runs out (usually 2-3 months).
4.  Once activated, create a new project named `TradingBot`.

### 2. Create the Virtual Machine (VM)
1.  In the left menu (Hamburger icon ☰), go to **Compute Engine** > **VM instances**.
2.  Click **"Enable API"** if asked (wait ~1 minute).
3.  Click **"Create Instance"**.
4.  **Name:** `trading-bot-vps`.
5.  **Region:** Select `us-central1` (Iowa) or `us-east1` (South Carolina). These are usually cheapest.
6.  **Machine configuration:**
    - **Series:** E2
    - **Machine type:** `e2-medium` (2 vCPU, 4GB memory).
    - *Note: This provides good performance for MT5 + Python.*
7.  **Boot disk (CRITICAL STEP):**
    - By default, it selects "Debian" (Linux). **YOU MUST CHANGE THIS.**
    - Click the **"CHANGE"** button.
    - **Operating system:** Select **"Windows Server"** from the list.
    - **Version:** Select **"Windows Server 2022 Datacenter"** (Desktop Experience).
    - **Boot disk type:** Balanced persistent disk.
    - **Size:** 50 GB.
    - Click **"SELECT"** (blue button at bottom).
8.  **Firewall:**
    - Check "Allow HTTP traffic".
    - Check "Allow HTTPS traffic".
9.  Click **"Create"** (at the bottom).

### 3. Connect via RDP (Remote Desktop)
1.  Wait for the instance to show a green checkmark ✅.
2.  Look at the **Connect** column. Click the arrow 🔽 next to **"RDP"**.
3.  Select **"Set Windows password"**.
    - Username: `admin` (or keep default).
    - Click **"Set"**.
    - **COPY THE PASSWORD IMMEDIATELY.** You will not see it again. Save it in a notepad.
4.  Click the arrow 🔽 next to **"RDP"** again and select **"Download the RDP file"**.
5.  Open the downloaded file (`.rdp`).
6.  Click **Connect**.
7.  Paste the password you copied.
8.  Accept the certificate warning (Click Yes).
9.  You are now inside your remote Windows computer! 🖥️

---

## 🛠️ Phase 2: Setup Environment (Inside the VPS)

Perform these steps **inside** the remote desktop window.

### 1. Disable IE Enhanced Security (Stop Popups)
1.  The "Server Manager" usually opens automatically. If not, click Start > Server Manager.
2.  Click **"Local Server"** in the left menu.
3.  Find **"IE Enhanced Security Configuration"** (on the right). It usually says "On".
4.  Click "On", switch both options to **Off**, and click OK.
5.  Open Internet Explorer (or Edge) and download **Chrome** (search "download chrome"). Use Chrome for the rest.

### 2. Install Required Software
1.  **Install Python (CRITICAL):**
    - **DO NOT** download the latest version (like 3.13, 3.14, etc.). They will fail with MT5.
    - **Download exactly this version:** [Python 3.10.11](https://www.python.org/ftp/python/3.10.11/python-3.10.11-amd64.exe).
    - **IMPORTANT:** On the first screen of the installer, check the box **"Add Python to PATH"**.
    - Click "Install Now".
    - *(If you get error 0x80070659, see Troubleshooting at the bottom)*.
2.  **Install Git:**
    - Download [Git for Windows](https://git-scm.com/download/win).
    - Click Next, Next, Next... Install (Defaults are fine).
3.  **Install MetaTrader 5 (MT5):**
    - Download the MT5 installer from your broker (e.g., Deriv).
    - Install it and **Log in** to your trading account.
    - **IMPORTANT:** Enable AutoTrading in MT5:
        - Go to Tools > Options > Expert Advisors.
        - Check "Allow algorithmic trading".
        - Check "Allow DLL imports".
        - Click OK.

---

## 🚀 Phase 3: Deploy & Run the Bot

### 1. Clone Your Code
1.  Open **Command Prompt** (cmd) or PowerShell on the VPS.
2.  Run these commands:
    ```cmd
    cd Documents
    git clone https://github.com/<YOUR_USERNAME>/<YOUR_REPO_NAME>.git
    cd <YOUR_REPO_NAME>
    ```
    *(Replace `<YOUR_USERNAME>` and `<YOUR_REPO_NAME>` with your actual GitHub details).*

### 2. Install Dependencies
1.  In the same terminal (inside your project folder), run these commands one by one:
    ```cmd
    python -m venv venv
    venv\Scripts\activate
    pip install -r requirements.txt
    ```
    *(Note: The second command activates the virtual environment. You will see `(venv)` at the start of the line).*

### 3. Configure .env
1.  You need your `.env` file (it's not on GitHub for security).
2.  Right-click in the folder > New > Text Document.
3.  Name it `.env`.
4.  Open it and paste your login/server details.
5.  **CRITICAL FOR DATABASE:**
    - You MUST use a remote MongoDB (like MongoDB Atlas).
    - Add this line to your `.env` file:
      ```
      MONGO_URI=mongodb+srv://<username>:<password>@cluster0.example.mongodb.net/?retryWrites=true&w=majority
      ```
    - **IMPORTANT:** Go to your MongoDB Atlas Dashboard > Network Access > Add IP Address > **"Allow Access from Anywhere" (0.0.0.0/0)**.
    - *Security Note:* For a production environment, it is more secure to find the static IP address of your VPS and add only that IP address to the allow list. "Allow Access from Anywhere" is simpler for setup but less secure.
    - If you don't do this, the VPS cannot connect to the database.
6.  Save and close.

### 4. Start the Bot
1.  Double-click `start_bot.bat`.
2.  The bot should start, connect to MT5, and begin trading!

### 5. Keep it Running 24/7
- **DO NOT** click "Shut Down" or "Log Off" on the VPS.
- **DO** simply close the RDP window (click the X at the top).
- This "disconnects" you, but leaves the computer running with your bot active.

## 🛑 Troubleshooting

### MT5 Initialize Failed (Error -10003)
This means the bot cannot find your MetaTrader 5 terminal.
1.  **Find your MT5 Path:**
    - Right-click the **MetaTrader 5 icon** on your desktop (the one you use to open it).
    - Select **Properties**.
    - Look at the **Target** field. It will look like `"C:\Program Files\Deriv - MetaTrader 5\terminal64.exe"`.
    - Copy this full path (without the quotes).
2.  **Update .env:**
    - Open your `.env` file.
    - Add a new line:
      ```
      MT5_PATH=C:\Program Files\Deriv - MetaTrader 5\terminal64.exe
      ```
    - (Paste your actual path).
3.  **Restart the Bot.**

### Python Installation Error 0x80070659 (Forbidden by system policy)
This is a Windows Server security setting. To fix it:
1.  **Unblock the Installer:**
    - Right-click the `python-3.10.11-amd64.exe` file.
    - Click **Properties**.
    - At the bottom, check the box **"Unblock"** (if visible).
    - Click **Apply** and **OK**.
2.  **Run as Administrator:**
    - Right-click the installer again.
    - Select **Run as Administrator**.
3.  **Install for All Users:**
    - If it still fails, run the installer again.
    - Select **Customize installation**.
    - Click Next until "Advanced Options".
    - Check **"Install for all users"**.
    - This will change the install location to `C:\Program Files\Python310`.
    - Click **Install**.
