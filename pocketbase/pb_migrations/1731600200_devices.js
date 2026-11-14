/// <reference path="../pb_data/types.d.ts" />
migrate(
  (app) => {
    const devices = new Collection({
      type: "base",
      name: "devices",
      listRule: "",
      viewRule: "",
      createRule: "",
      updateRule: "",
      deleteRule: "",
      fields: [
        { name: "device_id", type: "text", required: true },
        { name: "farm_id", type: "text", required: true },
        { name: "plot_id", type: "text", required: true },
        { name: "name", type: "text", required: false },
        { name: "last_seen", type: "text", required: false },
        { name: "latest_reading", type: "json", required: false },
      ],
    });
    app.save(devices);

    const readings = new Collection({
      type: "base",
      name: "device_readings",
      listRule: "",
      viewRule: "",
      createRule: "",
      updateRule: "",
      deleteRule: "",
      fields: [
        { name: "device_id", type: "text", required: true },
        { name: "farm_id", type: "text", required: false },
        { name: "plot_id", type: "text", required: false },
        { name: "ts", type: "text", required: true },
        { name: "soil_moisture", type: "number", required: true },
        { name: "humidity", type: "number", required: true },
        { name: "temperature", type: "number", required: true },
      ],
    });
    app.save(readings);
  },
  (app) => {
    for (const name of ["device_readings", "devices"]) {
      try {
        const col = app.findCollectionByNameOrId(name);
        app.delete(col);
      } catch {
        // ignore if not present
      }
    }
  }
);
