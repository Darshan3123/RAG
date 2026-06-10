import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shared.storage.mongo_client import _bids

col = _bids()
total         = col.count_documents({})
empty_city    = col.count_documents({"city": ""})
empty_contact = col.count_documents({"contact_person": ""})
bad_emd       = col.count_documents({"earnest_amount": ""})
missing_org   = col.count_documents({"organization_name": {"$exists": False}})
missing_off   = col.count_documents({"office_name": {"$exists": False}})
is_new_true   = col.count_documents({"is_new": True})

print(f"total records:       {total}")
print(f"empty city:          {empty_city}")
print(f"empty contact:       {empty_contact}")
print(f"earnest as string:   {bad_emd}")
print(f"missing org_name:    {missing_org}")
print(f"missing office_name: {missing_off}")
print(f"is_new = True:       {is_new_true}  (awaiting indexer)")
