-- Zugriffsregeln des Portals für die Haupt-Domain (VirtualHost), geladen über XMPP_MODULES.
--
--  * Räume, die im Portal angelegt wurden ("Portal-Räume"), sind nur mit Token erreichbar:
--    angemeldete Benutzer:innen oder eingeladene Gäste mit persönlichem Link. Ohne Token
--    beantworten wir die Raumanfrage an den Fokus mit "not-authorized"; Jitsi zeigt dann
--    "Warten auf Gastgeber" mit Anmelde-Knopf (TOKEN_AUTH_URL -> Portal-Login).
--  * Alle anderen Räume kann jede:r ohne Anmeldung eröffnen (sofern im Portal freigegeben).
--  * Aufnahmen (Jibri) nur in Portal-Räumen und nur mit Token, das "recording" erlaubt.
--
-- Die Liste der Portal-Räume schreibt das Portal nach /portal-rooms/rooms.json.
-- Fehlt die Datei oder ist sie unlesbar, gilt: Anmeldung überall erforderlich (sicherer Zustand).

local st = require "util.stanza";
local jid = require "util.jid";
local json = require "util.json";
local lfs = require "lfs";

local state_file = module:get_option_string("portal_rooms_file", "/portal-rooms/rooms.json");
local state = { anonymous = false, rooms = {} };
local loaded_mtime = nil;

local function load_state()
    local attr = lfs.attributes(state_file);
    if not attr then
        state = { anonymous = false, rooms = {} };
        loaded_mtime = nil;
        return state;
    end
    if attr.modification == loaded_mtime then
        return state;
    end
    local f = io.open(state_file, "r");
    if not f then return state; end
    local data = f:read("*a");
    f:close();
    local parsed = json.decode(data);
    if type(parsed) ~= "table" then
        module:log("warn", "Portal-Raumliste %s nicht lesbar, Anmeldung bleibt überall erforderlich", state_file);
        state = { anonymous = false, rooms = {} };
        return state;
    end
    local rooms = {};
    for _, name in ipairs(parsed.rooms or {}) do
        rooms[string.lower(name)] = true;
    end
    state = { anonymous = parsed.anonymous == true, rooms = rooms };
    loaded_mtime = attr.modification;
    module:log("info", "Portal-Raumliste geladen (Räume ohne Anmeldung: %s)", tostring(state.anonymous));
    return state;
end

local function room_name(room_jid)
    local node = jid.split(room_jid or "");
    return node and string.lower(node) or nil;
end

local function has_feature(session, feature)
    local features = session.jitsi_meet_context_features;
    if session.auth_token == nil or type(features) ~= "table" then
        return false;
    end
    local value = features[feature];
    return value == true or value == "true";
end

-- Raumanfrage an den Fokus (Jicofo): entscheidet, ob jemand ohne Token einen Raum betreten darf
module:hook("pre-iq/host", function(event)
    local stanza, session = event.stanza, event.origin;
    if stanza.attr.type ~= "set" then return; end
    local conference = stanza:get_child("conference", "http://jitsi.org/protocol/focus");
    if not conference or session.auth_token ~= nil then return; end
    local s = load_state();
    local name = room_name(conference.attr.room);
    if name and (s.rooms[name] or not s.anonymous) then
        module:log("info", "Raum %s erfordert Anmeldung (Sitzung ohne Token)", name);
        session.send(st.error_reply(stanza, "cancel", "not-authorized"));
        return true;
    end
end, 10);

-- Aufnahme und Livestream starten: nur in Portal-Räumen, nur mit passendem Token
module:hook("pre-iq/full", function(event)
    local stanza, session = event.stanza, event.origin;
    local jibri = stanza:get_child("jibri", "http://jitsi.org/protocol/jibri");
    if not jibri then return; end
    local action = jibri.attr.action and string.lower(jibri.attr.action);
    if action ~= "start" then return; end
    local mode = jibri.attr.recording_mode and string.lower(jibri.attr.recording_mode) or "";
    local feature = (mode == "file") and "recording" or "livestreaming";
    local name = room_name(jid.bare(stanza.attr.to));
    local s = load_state();
    if not (name and s.rooms[name] and has_feature(session, feature)) then
        module:log("info", "Aufnahme in Raum %s abgelehnt", tostring(name));
        session.send(st.error_reply(stanza, "auth", "forbidden"));
        return true;
    end
end, 20);

module:log("info", "Portal-Zugriffsregeln aktiv (%s)", state_file);
