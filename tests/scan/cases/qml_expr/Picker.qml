import QtQuick
import QtQuick.Controls

Item {
    id: root
    property string confirmText: "Done"
    property string mode: "Normal"
    readonly property string sourceName: {
        const source = info ? info.source : 0
        return Api.nameOf(source) || "Unknown source"
    }
    ComboBox {
        model: ["Fluid background", "Starfield", qsTr("Video")]
    }
    ComboBox {
        model: ["left", "right"]
    }
    FileDialog {
        nameFilters: ["Images (*.png *.jpg)", "All files (*)"]
    }
    Text {
        text: '      Picker is released under the MIT License
                     MIT License
   Permission is hereby granted'
    }
}
