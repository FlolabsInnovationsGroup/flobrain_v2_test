# FloBrain Monorepo

Welcome to the central repository for the FloBrain ecosystem. This monorepo hosts the active development pillars of the FloBrain architecture.

## ▶️ Try FloBrain V2 locally (demo)

Needs Python 3.11+ and Node.js 20+. Nothing else: no database server, no AI key.

- **Windows:** double-click `run-demo.bat`
- **macOS / Linux:** `./run-demo.sh`

It installs the Python and website packages the first time (a few minutes), builds a local demo company (Nile Labs), starts the API and the website, and opens <http://localhost:3000/w/signin>. Pick a seat (owner, admin, team lead, member) or take the guided tour. Details: [`docs/v2/DEMO.md`](./docs/v2/DEMO.md).

## 🚨 Active vs Legacy

**Active code lives in `/flobrain-*` directories.**
Legacy code is archived in `/legacy`. Please do not build new features in `/legacy`.

## 📂 Project Structure

### 1. [FloBrain Core](./flobrain-core) (The Brain)
The central intelligence layer. Handles logic, memory, and decision making.

### 2. [FloBrain Cloud](./flobrain-cloud)
The backend infrastructure providing API services, persistent storage, and heavy compute routing.

### 3. [FloBrain Robotics](./flobrain-robotics)
Firmware and control software for FloBrain-powered robots and devices.

### 4. [FloBrain Website](./flobrain-website)
The public face of FloBrain.

### 5. [Hardware](./hardware) & [Docs](./docs)
Hardware schematics and project documentation.

## 🗄 Legacy
Old firmware and frontend code is archived in `./legacy`.
