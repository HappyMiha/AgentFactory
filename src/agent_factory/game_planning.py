"""Manual local game-plan drafts over Core source and immutable backlog revisions.

No AI invocation, source rewrite, revision activation, approval or execution grant.
"""
import json
import re
import uuid
from .autonomous_mission import AutonomousMissionService, MissionPhase
from .backlog import BacklogProposal, ProposedItem
from .backlog_revisions import BacklogRevisionService, BacklogRevisionOrigin
from .local_games import bounded
from .mission_intake import AutonomousMissionIntakeService

POLICY = 'local-game-planning-v1'
FIELDS = ('genre','engine','platform','controls','goal','lose_rule','visual_style',
          'first_playable','assumptions','deferred_scope','cost_notes')
GENRES = {
    'platformer': ('Jump to a reachable exit on one small platform level.',
                   'Arrow keys move; Space jumps.',
                   'Falling below the level restarts the attempt.'),
    'collector': ('Collect three visible tokens and reach an exit in one room.',
                  'Arrow keys move the player.',
                  'Touching an obstacle resets the current attempt.'),
    'puzzle': ('Solve one small tile arrangement with a visible target.',
               'Click a tile to make one legal move.',
               'An illegal move leaves the puzzle state unchanged.'),
}

class PlanningConflict(ValueError):
    pass


def validate_fields(fields):
    if not isinstance(fields,dict) or set(fields) != set(FIELDS):
        raise ValueError('invalid_plan_fields')
    for name in FIELDS:
        bounded(fields[name],1500,empty=True)
    if fields['genre'] not in GENRES or fields['engine'] not in ('godot','unity','unreal') or fields['platform'] not in ('windows','web'):
        raise ValueError('unsupported_plan_choice')


def template(genre='collector'):
    if genre not in GENRES:
        raise ValueError('unsupported_genre')
    goal,controls,lose=GENRES[genre]
    return {'genre':genre,'engine':'godot','platform':'windows','controls':controls,
            'goal':goal,'lose_rule':lose,'visual_style':'Readable placeholder shapes.',
            'first_playable':goal,'assumptions':'Manual template suggestion: one player, one small scene. Review every field against your source.',
            'deferred_scope':'Keep the rest of the original ambition for separately reviewed later milestones.',
            'cost_notes':'No AI call or paid operation has run. Execution costs and budget require separate qualification and approval.'}


def questions(fields):
    prompts={'controls':'Which exact inputs does the player use?',
             'goal':'What observable action completes this first goal?',
             'lose_rule':'What happens on a failed or invalid attempt?',
             'first_playable':'What is the smallest complete playable loop?',
             'visual_style':'Which placeholder style makes the goal readable?',
             'assumptions':'Which assumptions need your review?',
             'deferred_scope':'Which ambitions belong to a later milestone?',
             'cost_notes':'Which costs and limits still need approval?'}
    return [{'field':key,'question':question} for key,question in prompts.items() if not fields[key].strip()]


def proposal(fields, source):
    validate_fields(fields)
    trace=f'core-source:{source.id}:v{source.version}:sha256:{source.source_digest}'
    steps=[
      ('scene','Prepare the declared first scene',(),
       ('The '+fields['engine']+' project opens for the '+fields['platform']+' target.',
        'The scene implements only this first playable: '+fields['first_playable']),('first_playable','engine','platform')),
      ('input','Implement the declared player input',('scene',),
       ('These controls work: '+fields['controls'],),('controls','genre')),
      ('rules','Implement goal and failure rules',('input',),
       ('Success follows this goal: '+fields['goal'],'Failure or invalid input follows: '+fields['lose_rule']),('goal','lose_rule','genre')),
      ('verify','Verify the complete repeatable loop',('rules',),
       ('An input-driven test reaches the declared goal.','An incomplete attempt cannot report success.',
        'Observed failure and retained state follow exactly this declared rule: '+fields['lose_rule'],'The visual direction stays readable: '+fields['visual_style']),('goal','controls','lose_rule','visual_style')),
      ('delivery','Check an exported build without publication',('verify',),
       ('The '+fields['platform']+' build opens outside the editor and repeats the same input/goal checks.',
        'Record source/build digests and test evidence; do not publish.'),('platform','first_playable')),
    ]
    items=[]
    for key,title,deps,criteria,links in steps:
        items.append(ProposedItem(stable_id='game/'+key,kind='task',title=title,
            description='Manual draft for '+fields['genre']+'. Assumptions: '+fields['assumptions'],
            dependencies=tuple('game/'+dep for dep in deps),acceptance_criteria=criteria,
            source_references=(trace,)+tuple('game-plan-field:'+name for name in links),
            review_notes=('Template suggestions require human review; not extracted AI requirements.',),
            labels=('planning:manual-draft','game-genre:'+fields['genre']),priority='P1',
            validation_method=('Record input-driven evidence for each stated criterion.',),
            required_components=('Selected engine project and game source',),
            required_infrastructure=('Separately qualified engine, worker and model route',),
            expected_artifacts=('Source, test evidence and build manifest',),
            definition_of_done=('All stated criteria have independently reviewed evidence.',),
            assigned_role='Developer' if key not in ('verify',) else 'QA'))
    return BacklogProposal(source_path='core-source:'+str(source.id),source_sha256=source.content_digest,
        source_name=source.source_name,items=tuple(items),schema_version=2,
        source_metadata={'game_planning':{'policy':POLICY,'fields':dict(fields),'source_id':source.id,
                                        'source_version':source.version,'source_digest':source.source_digest}})


class GamePlanning:
    def __init__(self,storage):
        self.storage=storage
        self.revisions=BacklogRevisionService(storage)
        self.intake=AutonomousMissionIntakeService(storage)

    def _mission(self,mission_id,actor):
        mission=AutonomousMissionService(self.storage).get(mission_id)
        if mission.mission_owner != actor:
            raise KeyError('plan_not_found')
        return mission

    def _latest(self,mission_id):
        return self.storage.db.execute('SELECT * FROM autonomous_backlog_revisions WHERE mission_id=? ORDER BY revision_number DESC LIMIT 1',(mission_id,)).fetchone()

    def view(self,mission_id,actor,revision_id=None):
        mission=self._mission(mission_id,actor)
        source=self.intake.current_source(mission_id)
        latest=self._latest(mission_id)
        row=latest
        if revision_id is not None:
            row=self.storage.db.execute('SELECT * FROM autonomous_backlog_revisions WHERE id=? AND mission_id=?',(revision_id,mission_id)).fetchone()
            if row is None:raise KeyError('plan_not_found')
        meta=None
        if row:
            meta=json.loads(row['snapshot_json']).get('source',{}).get('game_planning')
            if not isinstance(meta,dict) or meta.get('policy') != POLICY:
                raise PlanningConflict('existing_revision_uses_another_planning_workflow')
        fields=meta['fields'] if meta else template()
        document=proposal(fields,source)
        tasks=[item.to_dict() for item in self.revisions.get_revision(row['id']).items] if row else [item.to_dict() for item in document.items]
        stale=bool(meta and meta['source_digest'] != source.source_digest)
        return {'mission_id':mission.id,'title':mission.name,'revision_id':row['id'] if row else None,
            'latest_revision_id':latest['id'] if latest else None,'source_id':source.id,'source_version':source.version,
            'source_digest':source.source_digest,'source_text':source.content[:12000],'source_preview_truncated':len(source.content)>12000,
            'fields':fields,'tasks':tasks,'questions':questions(fields)[:3],'unresolved_count':len(questions(fields)),
            'bound_source_id':meta['source_id'] if meta else source.id,
            'bound_source_version':meta['source_version'] if meta else source.version,
            'history':[dict(item) for item in self.storage.db.execute(
                'SELECT id,revision_number,created_at FROM autonomous_backlog_revisions WHERE mission_id=? ORDER BY revision_number DESC LIMIT 50',(mission_id,))],
            'stale':stale,'editable':mission.phase==MissionPhase.DRAFT and mission.active_execution_epoch_id is None,
            'planning_mode':'manual_template_draft','ai_plan_accepted':False,'execution_ready':False,
            'next_action':'Review this draft, then use the existing Core approval/qualification workflow. Live cloud planning remains gated by AF-GC-018.'}

    def save(self,mission_id,actor,*,fields,command_id,expected_revision_id,expected_source_digest):
        validate_fields(fields)
        if type(expected_revision_id) is not int or not 0<=expected_revision_id<=9223372036854775807 or not isinstance(expected_source_digest,str) or not re.fullmatch('[0-9a-f]{64}',expected_source_digest):
            raise ValueError('invalid_plan_version')
        try: command=str(uuid.UUID(command_id))
        except (ValueError,TypeError,AttributeError):raise ValueError('invalid_plan_command') from None
        with self.storage.db:
            # Existing authority joins this writer transaction: source/parent checks
            # and immutable revision creation cannot race another Core writer.
            self.storage._begin_immediate()
            mission=self._mission(mission_id,actor)
            if mission.phase!=MissionPhase.DRAFT or mission.active_execution_epoch_id is not None:
                raise PlanningConflict('mission_is_not_an_editable_draft')
            source=self.intake.current_source(mission_id)
            if source.source_digest!=expected_source_digest:raise PlanningConflict('source_changed')
            plan=proposal(fields,source)
            # Each explicit save is a distinct immutable draft, including reverts.
            plan.source_metadata['game_planning']['save_command_id']=command
            key='game-plan:'+str(mission_id)+':'+command
            replay=self.storage.db.execute('SELECT 1 FROM autonomous_backlog_commands WHERE command_id=?',(key,)).fetchone()
            if not replay:
                latest=self._latest(mission_id)
                if (latest['id'] if latest else 0)!=expected_revision_id:raise PlanningConflict('newer_plan_revision')
                if latest:
                    meta=json.loads(latest['snapshot_json']).get('source',{}).get('game_planning',{})
                    if meta.get('policy')!=POLICY:raise PlanningConflict('existing_revision_uses_another_planning_workflow')
            revision=self.revisions.create_revision(mission_id=mission_id,proposal=plan,origin=BacklogRevisionOrigin.HUMAN,
                created_by=actor,command_id=key,rationale='Human-saved manual game planning draft; no approval or activation.',
                parent_revision_id=expected_revision_id or None)
        return self.view(mission_id,actor,revision.id)
