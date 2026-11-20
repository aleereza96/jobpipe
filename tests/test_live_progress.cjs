const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function harness(options = {}) {
  const source = fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8');
  const start = source.indexOf('async function refreshLiveResults(');
  const end = source.indexOf('async function pollRun(', start);
  assert.ok(start >= 0 && end > start);
  const calls = [];
  const context = {
    state: {view: 'jobs', liveRefreshAt: 0, liveRefreshBusy: false},
    loadStats: async () => calls.push('stats'),
    loadJobs: async () => calls.push('jobs'),
    ...options,
  };
  vm.runInNewContext(source.slice(start, end), context);
  return {...context, calls};
}

test('completed results refresh while the search is running, without waiting for completion', async () => {
  const h = harness();
  await h.refreshLiveResults(true, 10000);
  assert.deepEqual(h.calls, ['stats', 'jobs']);
  await h.refreshLiveResults(true, 15000);
  assert.equal(h.calls.length, 2);
  await h.refreshLiveResults(true, 20000);
  assert.deepEqual(h.calls, ['stats', 'jobs', 'stats', 'jobs']);
});

test('live refresh does not replace the jobs dataset while another page is open', async () => {
  const h = harness(); h.state.view = 'cv';
  await h.refreshLiveResults(true, 10000);
  assert.deepEqual(h.calls, ['stats']);
  await h.refreshLiveResults(false, 30000);
  assert.deepEqual(h.calls, ['stats']);
});

test('slow refreshes do not overlap and failures allow a later retry', async () => {
  let release;
  let starts = 0;
  const h = harness({loadStats: () => {starts++; return new Promise(resolve => {release = resolve;});}});
  const first = h.refreshLiveResults(true, 10000);
  await h.refreshLiveResults(true, 30000);
  assert.equal(starts, 1);
  release(); await first;
  assert.equal(h.state.liveRefreshBusy, false);
  let attempts = 0;
  const failure = harness({loadStats: async () => {if (++attempts === 1) throw new Error('temporary failure');}});
  await assert.rejects(failure.refreshLiveResults(true, 10000), /temporary failure/);
  assert.equal(failure.state.liveRefreshBusy, false);
  await failure.refreshLiveResults(true, 20000);
  assert.equal(attempts, 2);
  assert.deepEqual(failure.calls, ['jobs']);
});
