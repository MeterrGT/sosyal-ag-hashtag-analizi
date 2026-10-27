#!/usr/bin/env node
/**
 * Download a 48-hour window of Turkish hashtag posts from the Jetstream v2 archive.
 * Only UTC timestamp + extracted hashtag names are written to CSV; post text and
 * account identifiers are used in memory only and are never persisted.
 *
 * Required env var: JETSTREAM_API_KEY (raw key, never commit it).
 */
import { Jetstream } from '@bsky/jetstream';
import { franc } from 'franc-min';
import { createWriteStream } from 'node:fs';
import { copyFile, mkdir, rename, access } from 'node:fs/promises';
import { constants } from 'node:fs';
import { once } from 'node:events';
import path from 'node:path';

const SERVICE = 'https://jetstream.us-west.bsky.network';
const API_KEY = process.env.JETSTREAM_API_KEY;
const DATA_DIR = path.join('data');
const PARTIAL_FILE = path.join(DATA_DIR, 'posts_hashtags_48h.partial.csv');
const ARCHIVE_FILE = path.join(DATA_DIR, 'posts_hashtags_48h.csv');
const MAIN_FILE = path.join(DATA_DIR, 'posts_hashtags.csv');
const BACKUP_FILE = path.join(DATA_DIR, 'posts_hashtags_test_backup.csv');
const HASHTAG_RE = /#([\p{L}\p{N}_]+)/gu;

function csvEscape(value) {
  const text = String(value ?? '');
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function eventTimeMs(evt) {
  const raw = evt?.witnessedAt ?? evt?.time;
  if (typeof raw === 'number' && Number.isFinite(raw)) {
    // Jetstream timestamps are normally RFC3339 strings. This handles numeric microseconds too.
    if (raw > 1e14) return raw / 1000; // microseconds -> milliseconds
    return raw; // already milliseconds (or small test value)
  }
  if (typeof raw === 'string') {
    const parsed = Date.parse(raw);
    return Number.isFinite(parsed) ? parsed : NaN;
  }
  return NaN;
}

function isTurkish(record, text) {
  const langs = Array.isArray(record?.langs) ? record.langs.map(x => String(x).toLowerCase()) : [];
  if (langs.length > 0) return langs.includes('tr');
  if (text.trim().length < 20) return false;
  try {
    return franc(text) === 'tur';
  } catch {
    return false;
  }
}

async function fetchAllSegments(apiKey) {
  const all = [];
  let cursor;
  let pages = 0;
  while (true) {
    const url = new URL('/xrpc/network.bsky.jetstream.listSegments', SERVICE);
    url.searchParams.set('limit', '1000');
    if (cursor) url.searchParams.set('cursor', cursor);
    const response = await fetch(url, {
      headers: { Authorization: `Bearer ${apiKey}` },
    });
    if (!response.ok) {
      const detail = (await response.text()).slice(0, 500);
      throw new Error(`listSegments failed: HTTP ${response.status}. ${detail}`);
    }
    const body = await response.json();
    if (!Array.isArray(body.segments)) throw new Error('listSegments response did not contain a segments array.');
    all.push(...body.segments);
    pages += 1;
    console.log(`Archive metadata pages: ${pages}; segments listed: ${all.length.toLocaleString()}`);
    if (!body.cursor || body.cursor === cursor || body.segments.length === 0) break;
    cursor = body.cursor;
  }
  if (all.length === 0) throw new Error('Jetstream did not return any sealed archive segments.');
  all.sort((a, b) => Number(a.index) - Number(b.index));
  return all;
}

async function writeWithBackpressure(stream, line) {
  if (!stream.write(line)) await once(stream, 'drain');
}

async function main() {
  if (!API_KEY) {
    console.error('JETSTREAM_API_KEY environment variable is missing. Set it in this terminal; do not put it in this file or GitHub.');
    process.exitCode = 1;
    return;
  }

  await mkdir(DATA_DIR, { recursive: true });
  console.log('Connecting to Jetstream v2 archive (historical snapshot; no live 48-hour wait).');
  console.log('Fetching archive segment metadata to locate a 48-hour time window.');
  const segments = await fetchAllSegments(API_KEY);
  const latest = segments[segments.length - 1];
  const endUs = Number(latest.maxWitnessedAt);
  if (!Number.isFinite(endUs) || !Number.isFinite(Number(latest.maxSeq))) {
    throw new Error('Latest segment is missing maxWitnessedAt/maxSeq metadata.');
  }
  const startUs = endUs - 48 * 60 * 60 * 1_000_000;
  const startSegmentIndex = segments.findIndex(segment => Number(segment.maxWitnessedAt) >= startUs);
  if (startSegmentIndex < 0) throw new Error('Could not find a segment that overlaps the last 48 hours.');
  // Start at the beginning of the segment just before the boundary when possible;
  // exact event timestamps below filter the result back to the requested 48-hour window.
  const safeIndex = Math.max(0, startSegmentIndex - 1);
  const startSeq = Number(segments[safeIndex].minSeq);
  const endSeq = Number(latest.maxSeq);
  const startIso = new Date(startUs / 1000).toISOString();
  const endIso = new Date(endUs / 1000).toISOString();
  console.log(`Window UTC: ${startIso} through ${endIso}`);
  console.log(`Using archive sequence range ${startSeq.toLocaleString()}–${endSeq.toLocaleString()}.`);
  console.log('The archive download is metered in bytes. If the key quota is reached, the service may return HTTP 429.');

  const output = createWriteStream(PARTIAL_FILE, { encoding: 'utf8' });
  await writeWithBackpressure(output, 'timestamp_utc,hashtags\n');
  const jetstream = new Jetstream({ service: SERVICE, apiKey: API_KEY });
  let eventsSeen = 0;
  let postEvents = 0;
  let inWindowPosts = 0;
  let turkishPosts = 0;
  let savedPosts = 0;
  const startMs = startUs / 1000;
  const endMs = endUs / 1000;

  try {
    for await (const evt of jetstream.snapshot({
      collections: ['app.bsky.feed.post'],
      kinds: ['commit'],
      afterSeq: startSeq,
      beforeSeq: endSeq,
    })) {
      eventsSeen += 1;
      if (evt?.kind !== 'commit' || evt?.commit?.operation !== 'create' || evt?.commit?.collection !== 'app.bsky.feed.post') continue;
      postEvents += 1;
      const ms = eventTimeMs(evt);
      if (!Number.isFinite(ms) || ms < startMs || ms > endMs) continue;
      inWindowPosts += 1;
      const record = evt.commit.record ?? {};
      const text = typeof record.text === 'string' ? record.text : '';
      if (!text || !isTurkish(record, text)) continue;
      turkishPosts += 1;
      const tags = [...new Set([...text.matchAll(HASHTAG_RE)].map(match => match[1].toLocaleLowerCase('tr-TR')))].filter(Boolean);
      if (tags.length === 0) continue;
      const timestamp = new Date(ms).toISOString();
      await writeWithBackpressure(output, `${csvEscape(timestamp)},${csvEscape(tags.join('|'))}\n`);
      savedPosts += 1;
      if (savedPosts % 1000 === 0) {
        console.log(`Events ${eventsSeen.toLocaleString()} | posts in window ${inWindowPosts.toLocaleString()} | Turkish posts with hashtags saved ${savedPosts.toLocaleString()}`);
      }
    }
  } catch (error) {
    output.end();
    await once(output, 'close').catch(() => {});
    console.error(`Archive snapshot stopped before completion: ${error?.message ?? error}`);
    console.error('A partial file was kept as data/posts_hashtags_48h.partial.csv; do not treat it as complete.');
    process.exitCode = 1;
    return;
  }

  output.end();
  await once(output, 'close');
  if (savedPosts === 0) {
    console.error('No Turkish hashtag posts were saved. The primary CSV was not changed.');
    process.exitCode = 1;
    return;
  }

  await rename(PARTIAL_FILE, ARCHIVE_FILE);
  try {
    await access(MAIN_FILE, constants.F_OK);
    try {
      await access(BACKUP_FILE, constants.F_OK);
    } catch {
      await copyFile(MAIN_FILE, BACKUP_FILE);
    }
  } catch {
    // No previous test CSV to back up.
  }
  await copyFile(ARCHIVE_FILE, MAIN_FILE);

  console.log('\nHistorical archive collection completed.');
  console.log(`Window UTC: ${startIso} through ${endIso}`);
  console.log(`Events decoded: ${eventsSeen.toLocaleString()}`);
  console.log(`Post create events: ${postEvents.toLocaleString()}`);
  console.log(`Posts in exact 48-hour window: ${inWindowPosts.toLocaleString()}`);
  console.log(`Turkish posts: ${turkishPosts.toLocaleString()}`);
  console.log(`Hashtag posts saved: ${savedPosts.toLocaleString()}`);
  console.log(`Archive CSV: ${ARCHIVE_FILE}`);
  console.log(`Analysis input updated: ${MAIN_FILE}`);
  console.log(`Previous test CSV backup (if it existed): ${BACKUP_FILE}`);
  console.log('Reminder: the API key is a secret; do not commit it or screenshots containing it.');
}

main().catch(error => {
  console.error(error?.stack ?? error);
  process.exitCode = 1;
});
