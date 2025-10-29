

## **FRC Remote Driver Station Control System**

### **Overview**

This application enables multiple laptops on the same local network to remotely **enable**, **disable**, and **monitor** a **dedicated FRC Driver Station PC** running the official FRC Driver Station software. The system provides a lightweight client application for laptops and a server daemon on the Driver Station machine. The main focus is **safety**, **low latency**, and **resilience**—the robot should immediately disable if network communication is lost.

---

### **System Architecture**

The system consists of two main components:

#### 1. **Driver Station Server (Host)**

- Runs on the dedicated Driver Station PC.

- Interfaces with the real **FRC Driver Station application** via two supported modes:
  - **Keystroke mode**: Simulated keyboard events or Win32 API automation
  - **FMS mode**: UDP packets mimicking the Field Management System protocol

- Hosts a **local UDP server** to receive commands from remote laptops (protocol supports UDP/TCP transport).

- Automatically **disables the robot** if:
  
  - No heartbeat (keepalive) signal is received from any authorized client within a defined timeout (e.g., 250 ms).
  
  - A disconnect or invalid message is detected.

#### 2. **Remote Control Client (Laptop)**

- Lightweight desktop application (or even a web-based frontend served by the server).

- Allows operators to:
  
  - See current Driver Station status (Enabled / Disabled / E-Stop / Connection state).
  
  - Enable / Disable / E-Stop the robot remotely.
  
  - Optionally view the Driver Station screen (via VNC).

- Periodically sends a **keepalive packet** to maintain authority and safety compliance.

- Uses a minimal UI optimized for low latency and clarity.

---

### **Communication Protocol**

- **Transport:** UDP for low latency, or TCP for reliability (optional dual-mode fallback).

- **Message Types:**
  
  - `HELLO`: client connects and authenticates.
  
  - `HEARTBEAT`: periodic signal to indicate connection alive.
  
  - `COMMAND`: enable / disable / e-stop.
  
  - `STATUS`: server → client update with robot/DS state.

- **Safety Rules:**
  
  - If no `HEARTBEAT` within 250 ms, immediately send disable key event.

---

### **Driver Station Control Interface**

- **Input Emulation:** Send keypresses (`[ + ] + \` to enable, `Enter` to disable.) using `pyautogui` or Windows API (`SendInput`) to control enable/disable.

- **Status Detection:** Use `pygetwindow` or screen OCR to detect current DS state (optional but useful).

---

### **More Features**

- **VNC Integration:**
  
  - Launches an VNC session for manual control(shows only DS window).
  
  - Could use a lightweight VNC server for live preview without full desktop sharing.

- **Multi-client Safety Mode:**
  
  - If all clients disconnect, server auto-disables robot.

---

### **Technology Stack**

- **Server (Driver Station PC):**
  
  - Language: Python (for fast prototyping and easy automation via Win32 APIs).
  
  - Libraries: `socket`, `keyboard` or `pyautogui`, `fastapi` .

- **Client:**
  
  - Language: Python
  
  - Libraries: `socket`, `asyncio`

---

### **Safety Design**

1. **Heartbeat Mechanism:**  
   The client sends a heartbeat every 100 ms. If the server misses 2 consecutive heartbeats, it triggers disable.

2. **Fail-Safe Default:**  
   Any connection loss, invalid packet, or client crash causes immediate disable.

3. **Operator Priority:**  
   Local keyboard inputs always override network commands.

4. **Logging:**  
   All enable/disable events are logged with timestamps and client identifiers.

---

### **User Workflow**

1. Driver Station boots and starts the **Remote DS Server** automatically.

2. Laptops on the network launch the **Remote DS Client**.

3. A client connects, authenticates, and requests control.

4. Operator enables/disables robot remotely.

5. If connection is interrupted or client quits, the robot is instantly disabled.

6. Occasionally, operator can open an RDP session to tweak DS settings or team number.

---

### **Example Scenario**

- The Driver Station is in a secure cabinet connected to the robot via Ethernet.

- Multiple laptops are in the driver area over Wi-Fi.

- The main operator uses a laptop to enable/disable the robot remotely.

- Another laptop monitors status for debugging.

- If Wi-Fi drops for any reason, the system automatically disables the robot to ensure safety.
