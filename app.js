/**
 * Kalpi Portfolio Trade Execution Engine - Vanilla JS Frontend Application
 * 
 * Target Backend: FastAPI running at http://localhost:8000
 * Endpoints matched:
 * - GET  /api/v1/health            -> System health check
 * - GET  /api/v1/brokers           -> List supported brokers & adapter status
 * - POST /api/v1/portfolios/execute -> Execute portfolio orders with Idempotency-Key
 */

// ==========================================
// API CONFIGURATION
// ==========================================
const API_BASE = "http://localhost:8000";

// Endpoint configurations (Adjust here if backend routes change)
const ENDPOINTS = {
  health: `${API_BASE}/api/v1/health`,
  brokers: `${API_BASE}/api/v1/brokers`,
  execute: `${API_BASE}/api/v1/portfolios/execute`
};

// ==========================================
// APPLICATION STATE
// ==========================================
let state = {
  selectedBroker: "mock",
  connectedBroker: "mock",
  isBrokerConnected: true,
  targetPortfolio: [],
  proposedOrders: [],
  lastExecutionResult: null
};

// Default sample portfolio for demonstration
const SAMPLE_TARGET_PORTFOLIO = [
  { symbol: "RELIANCE", target_quantity: 10, side: "BUY", action: "BUY", order_type: "MARKET" },
  { symbol: "INFY", target_quantity: 25, side: "BUY", action: "ADJUST", order_type: "MARKET" },
  { symbol: "TCS", target_quantity: 5, side: "SELL", action: "SELL", order_type: "MARKET" },
  { symbol: "HDFCBANK", target_quantity: 15, side: "BUY", action: "BUY", order_type: "MARKET" }
];

// Mock current holdings for comparison calculation demo
const MOCK_CURRENT_HOLDINGS = {
  "INFY": 20,
  "TCS": 10,
  "HDFCBANK": 0,
  "RELIANCE": 0
};

// ==========================================
// INITIALIZATION & EVENT LISTENERS
// ==========================================
document.addEventListener("DOMContentLoaded", () => {
  initEventListeners();
  checkBackendHealth();
  // Load default sample portfolio so UI is immediately testable
  loadTargetPortfolio(SAMPLE_TARGET_PORTFOLIO);
});

function initEventListeners() {
  // Upload button
  document.getElementById("btn-upload").addEventListener("click", handlePortfolioUpload);
  
  // Connect broker button
  document.getElementById("btn-connect-broker").addEventListener("click", handleConnectBroker);
  document.getElementById("btn-disconnect-broker").addEventListener("click", handleDisconnectBroker);
  
  // Execute trades button
  document.getElementById("btn-execute").addEventListener("click", handleExecuteTrades);

  // Radio button toggle listener
  document.querySelectorAll('input[name="execution_type"]').forEach(radio => {
    radio.addEventListener("change", calculateComparisonAndProposedTrades);
  });
}

// ==========================================
// BACKEND HEALTH CHECK
// ==========================================
async function checkBackendHealth() {
  try {
    const res = await fetch(ENDPOINTS.health);
    if (!res.ok) throw new Error(`HTTP Error ${res.status}`);
    showBanner("Backend connected successfully at " + API_BASE, "success");
  } catch (err) {
    showBanner(`Backend unreachable at ${API_BASE}. Please start backend server.`, "error");
  }
}

// ==========================================
// STEP 1: PORTFOLIO UPLOAD LOGIC
// ==========================================
function handlePortfolioUpload() {
  const fileInput = document.getElementById("portfolio-file");
  const feedback = document.getElementById("upload-feedback");
  feedback.innerHTML = "";

  if (!fileInput.files || fileInput.files.length === 0) {
    feedback.innerHTML = `<span class="status-badge danger">Error</span> Please select a CSV or JSON file to upload.`;
    return;
  }

  const file = fileInput.files[0];
  const reader = new FileReader();

  reader.onload = function(e) {
    try {
      let parsedData = [];
      const content = e.target.result;

      if (file.name.endsWith(".json")) {
        parsedData = JSON.parse(content);
      } else if (file.name.endsWith(".csv")) {
        parsedData = parseCSV(content);
      } else {
        throw new Error("Unsupported file format. Please upload .csv or .json");
      }

      if (!Array.isArray(parsedData) || parsedData.length === 0) {
        throw new Error("File contains no valid portfolio rows.");
      }

      loadTargetPortfolio(parsedData);
      feedback.innerHTML = `<span class="status-badge success">Success</span> Uploaded ${parsedData.length} stocks from ${file.name}`;
      showBanner(`Target portfolio uploaded successfully (${parsedData.length} symbols).`, "success");
    } catch (err) {
      feedback.innerHTML = `<span class="status-badge danger">Upload Failed</span> ${err.message}`;
    }
  };

  reader.readAsText(file);
}

function parseCSV(text) {
  const lines = text.trim().split("\n");
  if (lines.length < 2) return [];

  const headers = lines[0].split(",").map(h => h.trim().toLowerCase());
  const rows = [];

  for (let i = 1; i < lines.length; i++) {
    if (!lines[i].trim()) continue;
    const values = lines[i].split(",").map(v => v.trim());
    const rowObj = {};
    
    headers.forEach((h, idx) => {
      rowObj[h] = values[idx];
    });

    const symbol = (rowObj.symbol || rowObj.ticker || "").toUpperCase();
    const targetQty = parseInt(rowObj.target_quantity || rowObj.quantity || rowObj.qty || "0", 10);
    const side = (rowObj.side || rowObj.action || "BUY").toUpperCase();

    if (symbol && targetQty > 0) {
      rows.push({
        symbol: symbol,
        target_quantity: targetQty,
        side: side.includes("SELL") ? "SELL" : "BUY",
        action: rowObj.action ? rowObj.action.toUpperCase() : (side.includes("SELL") ? "SELL" : "BUY"),
        order_type: "MARKET"
      });
    }
  }
  return rows;
}

function loadTargetPortfolio(portfolioData) {
  state.targetPortfolio = portfolioData;

  // Render Target Portfolio Table
  const tbody = document.querySelector("#table-target-portfolio tbody");
  tbody.innerHTML = "";

  portfolioData.forEach(item => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong>${item.symbol}</strong></td>
      <td>${item.target_quantity}</td>
      <td><span class="status-badge ${item.side === 'BUY' ? 'success' : 'danger'}">${item.side}</span></td>
      <td>${item.order_type || 'MARKET'}</td>
    `;
    tbody.appendChild(tr);
  });

  document.getElementById("target-portfolio-container").classList.remove("hidden");
  calculateComparisonAndProposedTrades();
}

// ==========================================
// STEP 2: CONNECT BROKER LOGIC
// ==========================================
async function handleConnectBroker() {
  const brokerSelect = document.getElementById("broker-select");
  const selectedBroker = brokerSelect.value;

  if (!selectedBroker) {
    alert("Please select a broker adapter from the dropdown.");
    return;
  }

  // Simulate broker authentication call
  try {
    state.selectedBroker = selectedBroker;
    state.connectedBroker = selectedBroker;
    state.isBrokerConnected = true;

    // Render Status Card
    document.getElementById("broker-status-card").classList.remove("hidden");
    document.getElementById("broker-status-text").textContent = `Connected (${selectedBroker.toUpperCase()})`;
    document.getElementById("broker-status-text").className = "status-badge success";
    document.getElementById("broker-mode-text").textContent = selectedBroker === "mock" ? "Runnable Mock Adapter" : `Scaffold Adapter (${selectedBroker})`;
    document.getElementById("broker-user-text").textContent = `user_${selectedBroker}_demo`;

    document.getElementById("btn-disconnect-broker").classList.remove("hidden");
    showBanner(`Successfully connected to broker adapter: ${selectedBroker.toUpperCase()}`, "success");
    
    // Highlight step 3
    setStepActive(3);
  } catch (err) {
    showBanner(`Broker connection failed: ${err.message}`, "error");
  }
}

function handleDisconnectBroker() {
  state.isBrokerConnected = false;
  state.connectedBroker = null;
  document.getElementById("broker-status-card").classList.add("hidden");
  document.getElementById("btn-disconnect-broker").classList.add("hidden");
  showBanner("Disconnected from broker.", "warning");
}

// ==========================================
// STEP 3: REVIEW & CALCULATE PROPOSED TRADES
// ==========================================
function calculateComparisonAndProposedTrades() {
  const comparisonTbody = document.querySelector("#table-comparison tbody");
  comparisonTbody.innerHTML = "";

  const executionTypeRadio = document.querySelector('input[name="execution_type"]:checked');
  const executionType = executionTypeRadio ? executionTypeRadio.value : "REBALANCE";

  state.proposedOrders = [];

  state.targetPortfolio.forEach(item => {
    const symbol = item.symbol;
    const targetQty = item.target_quantity;
    const currentQty = MOCK_CURRENT_HOLDINGS[symbol] || 0;
    const diff = targetQty - currentQty;
    
    let side = item.side || (diff >= 0 ? "BUY" : "SELL");
    let action = item.action || (diff > 0 && currentQty > 0 ? "ADJUST" : side);
    let orderQty = Math.abs(diff > 0 ? diff : (item.target_quantity || diff));

    // If execution_type is FIRST_TIME, only BUY orders are valid according to FastAPI backend validation rules
    if (executionType === "FIRST_TIME") {
      if (side !== "BUY") return; // Skip non-BUY orders for FIRST_TIME
      action = "BUY";
    }

    // Ensure action and side match Pydantic schema validation rules:
    // BUY action requires BUY side, SELL action requires SELL side
    if (action === "BUY") side = "BUY";
    if (action === "SELL") side = "SELL";

    // Construct valid order instruction matching FastAPI OrderInstruction schema
    state.proposedOrders.push({
      symbol: symbol,
      quantity: orderQty,
      side: side,
      action: action,
      order_type: "MARKET"
    });

    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong>${symbol}</strong></td>
      <td>${currentQty}</td>
      <td>${targetQty}</td>
      <td>${diff > 0 ? '+' + diff : diff}</td>
      <td><span class="status-badge ${side === 'BUY' ? 'success' : 'danger'}">${action} (${side})</span></td>
      <td>${orderQty}</td>
      <td>MARKET</td>
    `;
    comparisonTbody.appendChild(tr);
  });
}

// ==========================================
// STEP 3 & 4: EXECUTE TRADES LOGIC (API Call)
// ==========================================
async function handleExecuteTrades() {
  if (!state.isBrokerConnected) {
    alert("Please connect to a broker first in Step 2.");
    return;
  }

  if (!state.proposedOrders || state.proposedOrders.length === 0) {
    alert("No orders to execute. Please upload a target portfolio first.");
    return;
  }

  const executionType = document.querySelector('input[name="execution_type"]:checked').value;
  const spinner = document.getElementById("execute-spinner");
  const executeBtn = document.getElementById("btn-execute");

  // Generate unique Idempotency Key
  const idempotencyKey = `ui-exec-${Date.now()}`;

  // Payload matching FastAPI ExecutePortfolioRequest schema
  const payload = {
    broker: state.connectedBroker,
    execution_type: executionType,
    orders: state.proposedOrders
  };

  try {
    spinner.classList.remove("hidden");
    executeBtn.disabled = true;

    showBanner("Executing portfolio trades via FastAPI backend...", "warning");

    const response = await fetch(ENDPOINTS.execute, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey
      },
      body: JSON.stringify(payload)
    });

    const responseData = await response.json();

    if (!response.ok) {
      const errorMsg = responseData.detail || JSON.stringify(responseData);
      throw new Error(`API Execution Failed (${response.status}): ${errorMsg}`);
    }

    state.lastExecutionResult = responseData;
    renderExecutionResults(responseData);
    showBanner(`Execution completed successfully! ID: ${responseData.execution_id}`, "success");
    setStepActive(4);

    // Scroll to results
    document.getElementById("section-results").scrollIntoView({ behavior: 'smooth' });

  } catch (err) {
    showBanner(err.message, "error");
    alert(`Execution Error: ${err.message}`);
  } finally {
    spinner.classList.add("hidden");
    executeBtn.disabled = false;
  }
}

// ==========================================
// STEP 4: RENDER RESULTS & STATS
// ==========================================
function renderExecutionResults(result) {
  document.getElementById("stat-execution-id").textContent = result.execution_id || "--";
  
  const statusEl = document.getElementById("stat-overall-status");
  statusEl.textContent = result.status;
  statusEl.className = `stat-value ${result.status === 'SUCCESS' ? 'status-badge success' : 'status-badge danger'}`;

  document.getElementById("stat-success-count").textContent = result.successful_count;
  document.getElementById("stat-failed-count").textContent = result.failed_count;

  const tbody = document.querySelector("#table-results tbody");
  tbody.innerHTML = "";

  if (!result.results || result.results.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" class="empty-msg">No results returned.</td></tr>`;
    return;
  }

  result.results.forEach(item => {
    const tr = document.createElement("tr");
    const isSuccess = item.status === "ACCEPTED" || item.status === "SUCCESS";
    
    tr.innerHTML = `
      <td><code>${item.client_order_id}</code></td>
      <td><strong>${item.symbol}</strong></td>
      <td><span class="status-badge ${item.side === 'BUY' ? 'success' : 'danger'}">${item.side}</span></td>
      <td>${item.quantity}</td>
      <td><span class="status-badge ${isSuccess ? 'success' : 'danger'}">${item.status}</span></td>
      <td><code>${item.broker_order_id || '--'}</code></td>
      <td>${item.attempts || 1}</td>
      <td>${item.message || (isSuccess ? 'Accepted by mock broker' : 'Rejected')}</td>
    `;
    tbody.appendChild(tr);
  });
}

function handleRefreshStatus() {
  if (!state.lastExecutionResult) {
    alert("No execution has been performed yet.");
    return;
  }
  renderExecutionResults(state.lastExecutionResult);
  showBanner("Refreshed execution order status.", "success");
}

// ==========================================
// HELPER FUNCTIONS
// ==========================================
function showBanner(message, type) {
  const banner = document.getElementById("status-banner");
  banner.textContent = message;
  banner.className = `banner ${type}`;
  banner.classList.remove("hidden");
}

function setStepActive(stepNum) {
  document.querySelectorAll(".stepper .step").forEach((el, idx) => {
    if (idx + 1 <= stepNum) {
      el.classList.add("active");
    } else {
      el.classList.remove("active");
    }
  });
}
