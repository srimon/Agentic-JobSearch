"""One-time ownership transfer. Existing SMTP evidence is mandatory and never reset."""
from datetime import datetime
from .delivery_state import exclusive,read_json,atomic_json,require_known_deliveries

def initialize(directory,config,seed):
    if config.get('version')!=1 or config.get('owner')!='kubernetes':
        raise ValueError('Invalid workflow owner')
    if datetime.fromisoformat(config['not_before']).tzinfo is None:
        raise ValueError('Activation time requires an explicit timezone')
    with exclusive(directory,'daily-workflow.lock'),exclusive(directory,'report-dispatch.lock'):
        journal=directory/'email-delivery.jsonl'
        if not journal.is_file():raise RuntimeError('Restore SMTP journal before ownership transfer')
        require_known_deliveries(journal)
        if any(e.get('requires_reconciliation') for e in seed.values()):
            raise RuntimeError('Reconcile legacy daily dispatches before ownership transfer')
        owner=read_json(directory/'daily-owner.json')
        if owner:
            if owner!=config or not (directory/'daily-workflow.json').is_file():
                raise RuntimeError('Existing ownership does not match; refusing replacement')
            return 'already_initialized'
        existing=read_json(directory/'daily-workflow.json')
        if existing is not None and existing!=seed:
            raise RuntimeError('Workflow state already exists; refusing replacement')
        atomic_json(directory/'daily-workflow.json',seed)
        atomic_json(directory/'daily-owner.json',config)
        return 'initialized'
