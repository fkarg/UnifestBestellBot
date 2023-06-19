import * as mqtt from "mqtt";  // import everything inside the mqtt module and give it the namespace "mqtt"
let sound_a_file = require('./sound_a.mp3');

let hash = window.location.hash.substring(1);
let params = hash.split("|")

let filter = "tickets/" + params[0].toLocaleLowerCase();
let host = params[1];

let client = mqtt.connect('ws://' + host); // create a client

let sound_a = new Audio(sound_a_file);
let allow_play = false;

alert("Drücke irgendwo um in Vollbild zu wechseln. Wenn Sound nervig, den Tab muten.");
  
client.on('connect', function () {
    client.subscribe('#', { qos: 0 })
})
client.on('message', function (topic, message) {
  // message is Buffer
  message = message.toString();
  if (message == "") {
    return;
  }
  message = JSON.parse(message);
  if (topic.toLocaleLowerCase().startsWith(filter)) {
    handleTicket(message);
  }
})

function handleTicket(message) {
    let uid = message.uid;
    let ticketContainer = document.getElementById(uid);


    if (ticketContainer == null) {
        ticketContainer = document.createElement("div");
        ticketContainer.id = uid
        let container_tickets = document.getElementById("container-tickets");
        let first_ticket_container = container_tickets.firstChild;
        container_tickets.insertBefore(ticketContainer, first_ticket_container);


        let pTicketText = document.createElement("p");
        pTicketText.className = "ticket-text";
        ticketContainer.appendChild(pTicketText);
        let pTicketNo = document.createElement("p");
        pTicketNo.className = "ticket-no";
        ticketContainer.appendChild(pTicketNo);
    }

    ticketContainer.className = message.status;
    let secondary_text = "#" + message.uid;
    if (message.who) {
        secondary_text = message.who + " | " + secondary_text;
    }
    ticketContainer.lastChild.innerText = secondary_text;
    ticketContainer.firstChild.innerText = message.text;

    if (message.status == "CLOSED") {
        document.getElementById("container-tickets").removeChild(ticketContainer);
    }
    else if (message.status == "OPEN" && allow_play) {
        sound_a.play();
    }
}

function goFullscreen() {
    document.documentElement.requestFullscreen();
    allow_play = true;
}

document.documentElement.onclick = goFullscreen;