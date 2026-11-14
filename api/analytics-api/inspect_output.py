import json

with open('projection_api/sample_full_response.json', 'r') as f:
    data = json.load(f)

print('=== PARCEL & BASELINE CONTEXT ===')
print(f"Parcel ID: {data['cadastral_parcel_id']}")
print(f"Area: {data['field_area_ha']} hectares")
print(f"Resolved Soil Type: {data['resolved_soil_type']}")
print("Climate Baseline:", json.dumps(data['climate_baseline'], indent=2))

print('\n' + '='*80)
print('=== 5 CHAMPION ROTATION STRATEGIES ===')
print('='*80)

for strat_key, strat_val in data['strategies'].items():
    print(f"\n>>> STRATEGY: {strat_key.upper()} - '{strat_val['strategy_title']}'")
    print(f"Core Objective: {strat_val['core_objective']}")
    print(f"3-Year Sequence: {' -> '.join(strat_val['rotation_sequence'])}")
    
    cum = strat_val['cumulative_metrics']
    print("\n  [3-Year Cumulative Totals]")
    print(f"  • Gross Revenue:       ${cum['total_gross_revenue_usd']:>12,.2f}")
    print(f"  • Total Operating Cost:${cum['total_cost_usd']:>12,.2f}")
    print(f"  • Net Profit:          ${cum['total_net_profit_usd']:>12,.2f}")
    print(f"  • Cumulative ROI:       {cum['cumulative_roi_pct']:>11.1f}%")
    print(f"  • Total Labor:          {cum['total_labor_hours']:>11.1f} hours")
    print(f"  • Machinery Passes:     {cum['total_machinery_passes']:>11d} passes")
    print(f"  • Fuel Consumption:     {cum['total_diesel_liters']:>11.1f} liters")
    print(f"  • Total Irrigation:     {cum['total_irrigation_volume_m3']:>11.1f} m³")
    
    print("\n  [Soil Physics & Regenerative Condition at Year 3]")
    print(f"  • Soil Organic Carbon:  {cum['initial_soc_pct']:.2f}% ➔ {cum['final_soc_pct']:.2f}% (Net Δ: {cum['net_soc_change_pct']:+.2f}%)")
    print(f"  • Topsoil C Stock In:   {cum['total_carbon_input_tons_ha']:.2f} t C/ha")
    print(f"  • Subsoil Compaction:   {cum['initial_compaction_psi']:.1f} PSI ➔ {cum['final_compaction_psi']:.1f} PSI (Net Δ: {cum['net_compaction_change_psi']:+.1f} PSI)")
    print(f"  • Biological N Fixed:   {cum['total_biological_n_fixed_kg_ha']:.1f} kg N/ha")
    print(f"  • Fertilizer N Saved:  ${cum['synthetic_n_saved_usd']:,.2f}")
    print(f"  • Average Soil Erosion: {cum['average_annual_erosion_tons_ha']:.2f} tons/ha/year")
    print(f"  • Soil Health Score:    {cum['cumulative_soil_health_score']:.1f} / 100")
    print(f"  • Composite Loss Risk:  {cum['composite_loss_risk_score']:.1f} / 100")

    print("\n  [Year-by-Year Progression]")
    for yr in [strat_val['year_1'], strat_val['year_2'], strat_val['year_3']]:
        print(f"    Year {yr['year_index']} ({yr['crop_name']}):")
        print(f"      Yield: {yr['projected_yield_tons_ha']} t/ha ({yr['total_yield_tons']} t total) | Gross Rev: ${yr['gross_revenue_usd']:,.2f} | Net Profit: ${yr['net_profit_usd']:,.2f} (ROI: {yr['roi_pct']}%)")
        print(f"      Soil State: SOC {yr['soc_pct_start']:.2f}% ➔ {yr['soc_pct_end']:.2f}% ({yr['soc_change_pct']:+.2f}%) | Compaction: {yr['compaction_psi_start']:.1f} ➔ {yr['compaction_psi_end']:.1f} PSI ({yr['compaction_change_psi']:+.1f} PSI)")
        print(f"      N-Balance: {yr['nitrogen_balance_kg_ha']:+.1f} kg N/ha | Fixed: {yr['biological_n_fixed_kg_ha']} kg/ha | Synth N applied: {yr['synthetic_n_applied_kg_ha']} kg/ha")
        print(f"      Narrative: \"{yr['ground_narrative']}\"")

print('\n' + '='*80)
print('=== GEMINI AI ADVISORY REPORT ===')
print('='*80)
adv = data['gemini_advisory']
print("\n[EXECUTIVE SUMMARY]")
print(adv['executive_summary'])

print("\n[STRATEGY TRADEOFF MATRIX]")
print(adv['strategy_tradeoff_matrix'])

print("\n[ACTIONABLE FIELD CHECKLIST]")
for item in adv['ground_truth_field_checklist']:
    print(f"• {item}")
