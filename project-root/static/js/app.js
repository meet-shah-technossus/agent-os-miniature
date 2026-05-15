const statuses = ["Scheduled", "Completed", "Cancelled"];
const appointmentsBody = document.getElementById("appointments");
const totalEl = document.getElementById("total");
const completedEl = document.getElementById("completed");
const pendingEl = document.getElementById("pending");

async function fetchAppointments() {
  try {
    const response = await fetch("/api/appointments");
    if (!response.ok) {
      throw new Error("Failed to fetch appointments");
    }
    const appointments = await response.json();
    renderAppointments(appointments);
  } catch (error) {
    console.error(error);
  }
}

async function fetchSummary() {
  try {
    const response = await fetch("/api/summary");
    if (!response.ok) {
      throw new Error("Failed to fetch summary");
    }
    const summary = await response.json();
    totalEl.textContent = summary.total;
    completedEl.textContent = summary.completed;
    pendingEl.textContent = summary.pending;
  } catch (error) {
    console.error(error);
  }
}

function renderAppointments(appointments) {
  appointmentsBody.innerHTML = "";
  appointments.forEach((appointment) => {
    const row = document.createElement("tr");
    const time = new Date(appointment.appointment_time).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    });

    row.innerHTML = `
      <td>${appointment.patient_name}</td>
      <td>${time}</td>
      <td>${appointment.doctor_name}</td>
      <td><select data-id="${appointment.id}"></select></td>
      <td><button data-id="${appointment.id}">Update</button></td>
    `;

    const select = row.querySelector("select");
    statuses.forEach((value) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      option.selected = value === appointment.status;
      select.appendChild(option);
    });

    const button = row.querySelector("button");
    button.addEventListener("click", () => {
      handleStatusUpdate(appointment.id, select.value);
    });

    appointmentsBody.appendChild(row);
  });
}

async function handleStatusUpdate(id, status) {
  try {
    const response = await fetch(`/api/appointments/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.message || "Unable to save status");
    }
    await fetchAppointments();
    await fetchSummary();
  } catch (error) {
    console.error(error);
  }
}

fetchAppointments();
fetchSummary();
setInterval(() => {
  fetchAppointments();
  fetchSummary();
}, 3000);
