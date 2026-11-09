"""Non-destructive, explicit onboarding task selection."""
import re
TASKS = {
 "delivery": ("delivery_dates","detail_editor","Delivery dates","Confirm the scope and precision of each delivery date."),
 "parking": ("parking_and_storage","detail_editor","Parking and storage","Record confirmed details and what they apply to."),
 "review": (None,"complete","Profile review","Review the profile and explicitly approve pending changes when ready."),
 "meta_account": ("campaigns_defined","meta_lead_setup","Meta account","Review the saved Company authorization in step 1. Connecting an account does not link a campaign. Use step 2 to associate campaigns/forms."),
 "meta_assets": ("campaigns_defined","meta_lead_setup","Meta campaigns and forms","Review step 2 for this Project. Existing Company account permissions are reused; no route changes until explicit verification."),
 "team": ("sales_contacts","project_sales_team","Existing team","Assign existing users. Create users in Company onboarding or Team / Users; existing Project exceptions remain in force."),
 "catalog": ("property_type_catalog","property_type_catalog","Property types","Review, add or edit property types below. Deletion still requires explicit confirmation."),
 "documents": (None,"documents","Documents","Attach a new document using the attachment button. Choose its content and sharing permissions before approval."),
 "location": ("country","location_editor","Location and timezone","Review selectable country, city and IANA timezone suggestions. Confirm them explicitly; existing appointments will not be shifted."),
 "meta": (None,"meta_task_choice","Meta task","Do you want to reconnect an account or associate this Project's campaigns/forms? Choose one below."),
}
def detect_task(text):
    value = text.casefold().strip()
    if value == "open review: catalog": return "catalog"
    inventory_command = re.match(r"^(?:(?:okay|ok)[, ]+)?(?:(?:i (?:want|need) to|let[’']s|please)\s+)?(?:fill in|review|open|update|edit|change|confirm|revisar|abrir|actualizar|editar|cambiar|confirmar|completar)\b", value)
    if inventory_command and re.search(r"\b(available inventory|current inventory|disponibilidad|inventario)\b", value): return "catalog"
    if re.search(r"\b(review profile|review the profile|approve the company profile|approve company profile|approve profile|aprobar perfil|revisar perfil|revisar el perfil)\b",value): return "review"
    if not re.search(r"\b(update|edit|change|connect|reconnect|assign|add|upload|actualizar|editar|cambiar|conectar|reconectar|asignar|agregar|subir|quiero|want)\b",value):
        return None
    if re.search(r"\b(meta|facebook|campaña|campana|campaign|formulario)\b",value):
        if re.search(r"campaign|campaña|campana|formulario|form\b",value): return "meta_assets"
        if re.search(r"reconnect|reconectar|cuenta|account",value): return "meta_account"
        return "meta"
    for key,pattern in [("team",r"\b(team|users?|usuarios?|equipo|sales)\b"),("catalog",r"\b(units?|properties|property|unidades|tipolog|departamentos)"),("documents",r"\b(documents?|pdf|brochure|archivos?|documentos?)\b"),("location",r"\b(country|city|timezone|país|pais|ciudad|ubicación|zona horaria)\b")]:
        if re.search(pattern,value): return key
    return None

def question(task):
    field,kind,label,prompt = TASKS[task]
    if task=="parking":
        from app.modules.onboarding_questions import build_next_question
        result=build_next_question([{"field":field,"label":label,"requirement":"conditionally_required"}],final_prompt="Review")
        result.update(input_type=kind,task=task)
        return result
    return {"field":field,"input_type":kind,"label":label,"prompt":prompt,"options":[],"examples":[],
        "allow_custom":False,"task":task}

