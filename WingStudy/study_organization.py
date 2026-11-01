"""Presentation-only curation. Permanent study paths and cache identities stay valid."""
import json


def read(model):
    path=model.OUTPUTS.parent/'study_organization.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {'studies':{},'lambda_studies':[]}


def visible(config,study):
    return config.get('studies',{}).get(study,{}).get('group')!='retired'


def name(config,study,fallback=None):
    return config.get('studies',{}).get(study,{}).get('name',fallback or study)
