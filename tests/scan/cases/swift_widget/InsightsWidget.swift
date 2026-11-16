import SwiftUI
import WidgetKit

struct InsightsWidget: Widget {
    let kind: String = "InsightsWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: InsightsProvider()) { entry in
            InsightsWidgetEntryView(entry: entry)
        }
        .configurationDisplayName("Insights")
        .description("Analyse your expenditure breakdowns over various time periods.")
    }
}
