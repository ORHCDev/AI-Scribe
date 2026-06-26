import json

def get_referral_json():
    try: 
        with open(r".\utils\referral_form.json", "r") as f:
            data = json.load(f)
        return data
    except Exception as e:
        print("Failed to get read the referral form JSON file:", e)
        return None

def get_referral_labels():
    data = get_referral_json()

    truncated = {}

    for key, value in data.items():
        indications = value.get("indications", {})
        options = value.get("options", [])

        ind_arr = [ind["label"] for ind in indications.get("options", [])]
        opt_arr = [opt["label"] for opt in options]

        truncated[key] = {
            "options": opt_arr,
            "indications": ind_arr,
        }
    return truncated

def labels_to_ids(data):
    referral_form = get_referral_json()
    id_data = []
    for value in data:
        key = value.get("procedure")
        label_data = referral_form.get(key)
        if not label_data:
            continue
        label_id = label_data["id"]
        id_data.append({
            "type": "checkbox",
            "id": label_id,
            "name": label_id,
            "full_name": label_id,
            "value": label_id
        })
        ind_val = value.get("indications")
        ind_block = label_data.get("indications")
        if ind_val and ind_block:
            ind_id = ind_block["id"]
            ind_list = ind_block.get("options", [])
            for ind in ind_list:
                if ind["label"] == ind_val:
                    id_data.append({
                        "type": "text",
                        "id": ind_id,
                        "name": ind_id,
                        "full_name": ind_id,
                        "value": ind["id"]
                    })
                    break
        opt_val = value.get("options")
        if opt_val:
            for opt in label_data.get("options", []):
                if opt["label"] == opt_val:
                    id_data.append({
                        "type": "checkbox",
                        "id": opt["id"],
                        "name": opt["id"],
                        "full_name": opt["id"],
                        "value": opt["id"]
                    })
                    break
    print(id_data)
    return id_data


if __name__ == "__main__":
    #get_referral_labels()


    val = {
      "electrocardiogram": {
        "indications": "Chest pain of suspected cardiac origin.",
      },
      "holter monitor": {
        "indications": "symptom-rhythm correlation",
        "options": "24 Hours"
      }
    }
    labels_to_ids(val)

