import QtQuick 2.15

Item {
    property string hint: "x"
    Text {
        text: root.hints.back + ":BACK " + root.hints.select + ":SIGN IN"
    }
    Text {
        text: approved ? "Approved"
                    : (code !== "" ? "Waiting"
                                    : "Connecting")
    }
    Text { text: "TUNING " + channel.number }
    Row {
        label: authRoot.method === 1 ? "Email:" : "Username:"
        shuffleLabel: "Shuffled"
        cardTitle: listTitle + (listType === "collection_items" ? " (Collection)" : " (Playlist)")
    }
    Text { text: qsTr("Already routed") + suffix }
    Text { text: Qt.resolvedUrl("images/icon.png") }
    Text { text: value === "ON" ? onLabel : offLabel }
}
Item {
    Text { text: I18n.t("change", "CHANGE") }
    Text {
        text: connected ? I18n.t("status.on", "Connected to the private route")
                        : "Not connected yet"
    }
}
Item {
    Text { text: datePicker.selectedDate.toLocaleString(datePicker.locale, "dddd") }
}
