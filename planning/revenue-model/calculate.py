import csv,json,math
from pathlib import Path
P=Path(__file__).resolve().parent
# Success-only operating scenarios requested by the owner. Quantities and rates
# are editable planning inputs, not probability-weighted predictions or contracts.
scenarios=[('خدمات بالتعاون',[16,1,10,2,8]),('حزم مباشرة وإنتاج',[10,3,20,4,12]),('فريق متعدد الوكلاء',[20,5,50,6,20])]
# Segment, OPS, service scope, unit AED, fee, variable AED, human h/unit, agent h/unit
mix=[('خدمات كتابة ومستندات وبيانات','OPS012 / OPS013 / OPS029','DIG001–DIG018',1500,.15,30,1.5,4),('حزم مباشرة لعملاء','DIRECT001','DIG001–DIG018',6000,.03,150,4,12),('منتجات رقمية وتراخيص','OPS016 / OPS018 / OPS019','DIG002 / DIG011 / DIG018',150,.15,5,.1,.2),('جلسات وخدمات مشاركة حقيقية','OPS011 / OPS015 / OPS022 / OPS025 / OPS026','المشارك الحقيقي',350,.05,0,1.2,.1),('إحالات ومكافآت ومهام مدفوعة','OPS002 / OPS017 / OPS021 / OPS023 / OPS030','حسب عرض مستقل',100,.05,0,.5,.1)]
rows=[];totals=[]
for name,quantities in scenarios:
 for quantity,segment in zip(quantities,mix):
  seg,ops,dig,price,fee,var,h,a=segment
  gross=quantity*price
  rows.append({'scenario':name,'segment':seg,'ops':ops,'digital_types':dig,'units_week':quantity,'unit_price_aed':price,'success_probability':1,'collection_probability':1,'gross_week':gross,'fee_rate':fee,'fees_week':gross*fee,'variable_per_unit':0,'variable_week':0,'human_hours_per_unit':h,'agent_hours_per_unit':a,'human_hours_week':quantity*h,'agent_hours_week':quantity*a})
 r=[x for x in rows if x['scenario']==name]
 api=50*3.6725*7/30
 gross=sum(x['gross_week'] for x in r);fee=sum(x['fees_week'] for x in r);var=sum(x['variable_week'] for x in r)
 human=sum(x['human_hours_week'] for x in r);agent=sum(x['agent_hours_week'] for x in r)
 labor=0 # No hourly wage deducted in addition to the project agent share.
 agent_share=(gross-fee)*.30
 manager_share=(gross-fee)*.05
 net=gross-fee-var-api-labor-agent_share-manager_share
 margin=(gross-fee-var-labor-agent_share-manager_share)/gross
 totals.append({'scenario':name,'gross_day':gross/7,'gross_week':gross,'gross_30d':gross*30/7,'fees_week':fee,'variable_week':var,'api_reserve_week':api,'labor_allowance_week':labor,'agent_pool_rate':.30,'agent_pool_week':agent_share,'agent_pool_cap':.30,'manager_rate':.05,'manager_week':manager_share,'net_day':net/7,'net_week':net,'net_30d':net*30/7,'human_hours_week':human,'agent_hours_week':agent,'human_equivalents_30h':math.ceil(human/30),'gross_needed_for_18000_net_week':(18000+api)/margin,'contribution_margin':margin,'assumed_success_rate':1,'assumed_collection_rate':1,'timing':'Steady-state daily/weekly/30-day run rate; not a date promise for the first receipt.'})
for name,data in [('success-inputs',rows),('success-summary',totals)]:
 (P/(name+'.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
 with (P/(name+'.csv')).open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=data[0].keys());w.writeheader();w.writerows(data)
print(json.dumps(totals,ensure_ascii=False,indent=2))
