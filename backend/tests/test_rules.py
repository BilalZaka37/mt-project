from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.pipeline import AlertRules, inside_zone
from app.schemas import ZoneInput


def test_ground_contact_and_boundary():
    points=[[.2,.5],[.8,.5],[.8,.9],[.2,.9]]
    assert inside_zone([20,0,60,70],points,100,100)
    assert not inside_zone([20,0,60,40],points,100,100)
    assert inside_zone([20,0,60,50],points,100,100)


def test_entry_cooldown_exit_reentry_and_class_filter():
    rules=AlertRules()
    zone=SimpleNamespace(id=1,name='Door',points=[[.2,.2],[.8,.2],[.8,.8],[.2,.8]],classes=['person'])
    obj={'label':'person','track_id':1,'confidence':.9,'box':[20,10,60,60]}
    assert len(rules.evaluate([obj],[zone],100,100,0))==1
    assert not rules.evaluate([obj],[zone],100,100,20)
    rules.evaluate([],[zone],100,100,21)
    assert len(rules.evaluate([obj],[zone],100,100,22))==1
    rules.evaluate([],[zone],100,100,23)
    assert not rules.evaluate([obj],[zone],100,100,24)
    obj['label']='car'
    assert not rules.evaluate([obj],[zone],100,100,40)
    obj['label']='person';obj['track_id']=None
    assert not rules.evaluate([obj],[zone],100,100,50)


@pytest.mark.parametrize('points', [ [[0,0],[1,1]], [[0,0],[.5,.5],[1,1]], [[0,0],[1,1],[0,1],[1,0]], [[-1,0],[1,0],[0,1]], [[0,0],[1,0],[0,0]] ])
def test_invalid_polygons(points):
    with pytest.raises(ValidationError):
        ZoneInput(name='bad',points=points)


def test_detection_event_cooldown():
    rules=AlertRules()
    obj={'label':'person','track_id':1,'confidence':.9,'box':[20,10,60,60]}
    assert len(rules.evaluate([obj],[],100,100,0))==1
    assert not rules.evaluate([obj],[],100,100,1)
    assert len(rules.evaluate([obj],[],100,100,16))==1
