import QtQuick 2.15

Item {
    property string reason: "notfound"
    property string headline: {
        switch (reason) {
        case "notfound":   return "LOCATION NOT FOUND"
        case "network":    return "CAN'T REACH THE LOCATION SERVICE"
        default:           return "NO_LOCATION_KEY"
        }
    }
    property string detail: {
        if (reason === "network")
            return "Please check your network connection and try again"
        return ""
    }
}
