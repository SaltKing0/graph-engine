"""Authored regressions derived from exposed development inputs, never new gold."""
from copy import deepcopy

import pytest

from graph_engine.brain import Brain
from graph_engine.decision_service import DecisionService
from tools.decision_benchmark.production import execute, source_update
from test_decision_workflow import small_case


def replacement(visible: dict, event: dict, text: str) -> dict:
    result = deepcopy(visible)
    result['documents'] = [d for d in result['documents'] if d['source_id'] != event['source_id']]
    result['documents'].extend(dict(id=f"{event['source_id']}-c{i:03}", source_id=event['source_id'],
                                  text=text[start:start + 800])
                              for i, start in enumerate(range(0, len(text), 800)))
    return result


@pytest.mark.parametrize('crlf', [False, True])
def test_verified_noop_retains_update_source_and_original_accepted_basis(tmp_path, crlf):
    _, _, _, event, visible = small_case()
    basis = ''.join(d['text'] for d in visible['documents'] if d['source_id'] == event['changed_source_id'])
    visible = replacement(visible, event, basis.replace('\n', '\r\n') if crlf else basis)
    result = execute(visible, event, tmp_path / 'brain', 'curated', budget=4000, k=5)
    assert result['alerts'] == []
    audit = result['source_update']
    assert audit['classification'] == ('crlf_only' if crlf else 'identical')
    assert audit['old']['normalized_sha256'] == audit['new']['normalized_sha256']
    service = DecisionService(Brain(str(tmp_path / 'brain'), mode='git'))
    claim, = result['ids']['claims'].values()
    assert service.inspect(claim)['record']['previous'] is None
    update = next(d for d in visible['documents'] if d['source_id'] == event['source_id'])
    assert service.brain.read_node(update['id']).text == update['text'].replace('\r\n', '\n').strip()
    source = service.inspect(audit['captured_update_refs'][0])
    assert source['record']['anchor_node_id'] == update['id']
    assert source['state']['workflow'] == 'proposed'
    assert result['complete'] and result['context_within_budget']


@pytest.mark.parametrize('change', ['metric', 'spacing', 'description', 'negation'])
def test_semantic_or_unverified_formatting_changes_still_surface_unknown_scope(tmp_path, change):
    _, _, _, event, visible = small_case()
    basis = ''.join(d['text'] for d in visible['documents'] if d['source_id'] == event['changed_source_id'])
    text = {'metric': basis.replace('recall=0.8', 'recall=0.2'),
            'spacing': basis.replace('Choose mode', 'Choose  mode'),
            'description': 'Only blank-line formatting changed; the observations are unchanged.',
            'negation': basis.replace('Choose mode A', 'Do not choose mode A')}[change]
    visible = replacement(visible, event, text)
    result = execute(visible, event, tmp_path / 'brain', 'curated', budget=4000, k=5)
    assert result['source_update']['classification'] == 'changed'
    alert, = result['alerts']
    assert alert['uncertainty_reason'] and result['complete']


def test_noop_checks_all_chunks_including_crlf_across_chunk_boundary():
    event = dict(changed_source_id='basis', source_id='update')
    # These are engineering mutations, not independently annotated cases.
    original = dict(documents=[dict(id='basis-c000', source_id='basis', text='x' * 799 + '\nend')])
    visible = replacement(original, dict(source_id='basis'), 'x' * 799 + '\nend')
    visible = replacement(visible, event, 'x' * 799 + '\r\nend')
    assert source_update(list(reversed(visible['documents'])), event)['classification'] == 'crlf_only'
    visible['documents'][-1]['text'] += ' changed beyond chunk zero'
    assert source_update(visible['documents'], event)['classification'] == 'changed'


@pytest.mark.parametrize('damage', ['missing', 'duplicate', 'gap', 'short-prefix', 'empty'])
def test_incomplete_or_malformed_task_sources_cannot_establish_noop(damage):
    event = dict(changed_source_id='basis', source_id='update')
    visible = replacement(dict(documents=[]), dict(source_id='basis'), 'x' * 800 + 'end')
    visible = replacement(visible, event, 'x' * 800 + 'end')
    if damage == 'missing':
        visible['documents'] = [d for d in visible['documents'] if d['source_id'] != 'basis']
    elif damage == 'duplicate':
        visible['documents'].append(deepcopy(visible['documents'][-1]))
    elif damage == 'gap':
        visible['documents'][-1]['id'] = 'update-c002'
    elif damage == 'short-prefix':
        visible['documents'][-2]['text'] = 'short'
    else:
        visible['documents'][-1]['text'] = ''
    assert source_update(visible['documents'], event)['classification'] == 'unavailable'
