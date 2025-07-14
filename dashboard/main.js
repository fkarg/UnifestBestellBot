import * as mqtt from "mqtt";

let sound_a_file = require('./sound_a.mp3');

let hash = window.location.hash.substring(1);
let params = hash.split("|")

let filter = "tickets/" + params[0].toLocaleLowerCase();
// let host_port = params[1];
let mqtt_url = 'ws://162.55.42.21:8002/mqtt';
// let mqtt_url = 'ws://localhost:8002/mqtt';
// let mqtt_url = 'wss://domain:8002/mqtt'; // websocket connection with SSL

function createClient() {
    console.log('Connecting to:', mqtt_url);

    let client = mqtt.connect(mqtt_url, {
        protocolId: 'MQTT',
        protocolVersion: 4,
        clean: true,
        connectTimeout: 4000,
        reconnectPeriod: 1000
    });

    console.log('MQTT client identifier: ', client.options.clientId);

    return client;
}

function setupClientEvents(client) {
    client.on('connect', function () {
        console.log('MQTT connected successfully!', new Date().toISOString());
        client.subscribe('#', { qos: 0 });
    });

    client.on('error', function (error) {
        console.error('MQTT connection error:', error, new Date().toISOString());
    });

    client.on('close', function () {
        console.log('MQTT connection closed', new Date().toISOString());
    });

    client.on('offline', function () {
        console.log('MQTT client offline', new Date().toISOString());
    });

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
    });
}

let client = createClient(); // create a client
setupClientEvents(client);

let sound_a = new Audio(sound_a_file);
let allow_play = false;

alert("Drücke irgendwo um in Vollbild zu wechseln. Wenn Sound nervig, den Tab muten.");

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