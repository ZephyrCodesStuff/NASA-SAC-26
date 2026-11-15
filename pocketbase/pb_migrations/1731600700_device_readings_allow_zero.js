/// <reference path="../pb_data/types.d.ts" />
migrate(
  (app) => {
    const col = app.findCollectionByNameOrId("device_readings");
    for (const fieldName of ["soil_moisture", "humidity", "temperature"]) {
      const f = col.fields.getByName(fieldName);
      if (f) {
        f.required = false;
      }
    }
    app.save(col);
  },
  (app) => {
    const col = app.findCollectionByNameOrId("device_readings");
    for (const fieldName of ["soil_moisture", "humidity", "temperature"]) {
      const f = col.fields.getByName(fieldName);
      if (f) {
        f.required = true;
      }
    }
    app.save(col);
  }
);
