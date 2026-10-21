/**
 * Screen copy in Arabic, Turkish, French and Portuguese, keyed by the English sentence itself.
 *
 *   const tr = useTr();
 *   <h1>{tr("Download your data")}</h1>
 *   <p>{tr("{n} messages", { n: count })}</p>
 *
 * English is the source text, so a missing Arabic line falls back to English rather than a key.
 * When one English word means two things, prefix a context: `tr("state|Open")` shows "Open" in
 * English and has its own Arabic line, separate from the verb `tr("Open")`.
 * `phrases.test.ts` scans the screens and fails when a `tr("…")` string has no Arabic line.
 * Each language keeps one file per area in `messages/phrases/<language>/`.
 */

import { useCallback } from "react";

import { useLocale, type V2Locale } from "@/i18n";

import arAi from "../../messages/phrases/ar/ai.json";
import arAiadmin from "../../messages/phrases/ar/aiadmin.json";
import arCommon from "../../messages/phrases/ar/common.json";
import arCreate from "../../messages/phrases/ar/create.json";
import arDocs from "../../messages/phrases/ar/docs.json";
import arMeetings from "../../messages/phrases/ar/meetings.json";
import arPeople from "../../messages/phrases/ar/people.json";
import arPlatform from "../../messages/phrases/ar/platform.json";
import arPrivacy from "../../messages/phrases/ar/privacy.json";
import arRooms from "../../messages/phrases/ar/rooms.json";
import arSettings from "../../messages/phrases/ar/settings.json";
import arStudio from "../../messages/phrases/ar/studio.json";
import arTasks from "../../messages/phrases/ar/tasks.json";
import arWork from "../../messages/phrases/ar/work.json";
import arAutomations from "../../messages/phrases/ar/automations.json";
import arChannels from "../../messages/phrases/ar/channels.json";
import arData from "../../messages/phrases/ar/data.json";
import arConnectors from "../../messages/phrases/ar/connectors.json";
import arCrew from "../../messages/phrases/ar/crew.json";
import arAcademy from "../../messages/phrases/ar/academy.json";
import arVoice from "../../messages/phrases/ar/voice.json";
import frAi from "../../messages/phrases/fr/ai.json";
import frAiadmin from "../../messages/phrases/fr/aiadmin.json";
import frCommon from "../../messages/phrases/fr/common.json";
import frCreate from "../../messages/phrases/fr/create.json";
import frDocs from "../../messages/phrases/fr/docs.json";
import frMeetings from "../../messages/phrases/fr/meetings.json";
import frPeople from "../../messages/phrases/fr/people.json";
import frPlatform from "../../messages/phrases/fr/platform.json";
import frPrivacy from "../../messages/phrases/fr/privacy.json";
import frRooms from "../../messages/phrases/fr/rooms.json";
import frSettings from "../../messages/phrases/fr/settings.json";
import frStudio from "../../messages/phrases/fr/studio.json";
import frTasks from "../../messages/phrases/fr/tasks.json";
import frWork from "../../messages/phrases/fr/work.json";
import frAutomations from "../../messages/phrases/fr/automations.json";
import frChannels from "../../messages/phrases/fr/channels.json";
import frData from "../../messages/phrases/fr/data.json";
import frConnectors from "../../messages/phrases/fr/connectors.json";
import frCrew from "../../messages/phrases/fr/crew.json";
import frAcademy from "../../messages/phrases/fr/academy.json";
import frVoice from "../../messages/phrases/fr/voice.json";
import ptAi from "../../messages/phrases/pt/ai.json";
import ptAiadmin from "../../messages/phrases/pt/aiadmin.json";
import ptCommon from "../../messages/phrases/pt/common.json";
import ptCreate from "../../messages/phrases/pt/create.json";
import ptDocs from "../../messages/phrases/pt/docs.json";
import ptMeetings from "../../messages/phrases/pt/meetings.json";
import ptPeople from "../../messages/phrases/pt/people.json";
import ptPlatform from "../../messages/phrases/pt/platform.json";
import ptPrivacy from "../../messages/phrases/pt/privacy.json";
import ptRooms from "../../messages/phrases/pt/rooms.json";
import ptSettings from "../../messages/phrases/pt/settings.json";
import ptStudio from "../../messages/phrases/pt/studio.json";
import ptTasks from "../../messages/phrases/pt/tasks.json";
import ptWork from "../../messages/phrases/pt/work.json";
import ptAutomations from "../../messages/phrases/pt/automations.json";
import ptChannels from "../../messages/phrases/pt/channels.json";
import ptData from "../../messages/phrases/pt/data.json";
import ptConnectors from "../../messages/phrases/pt/connectors.json";
import ptCrew from "../../messages/phrases/pt/crew.json";
import ptAcademy from "../../messages/phrases/pt/academy.json";
import ptVoice from "../../messages/phrases/pt/voice.json";
import trAi from "../../messages/phrases/tr/ai.json";
import trAiadmin from "../../messages/phrases/tr/aiadmin.json";
import trCommon from "../../messages/phrases/tr/common.json";
import trCreate from "../../messages/phrases/tr/create.json";
import trDocs from "../../messages/phrases/tr/docs.json";
import trMeetings from "../../messages/phrases/tr/meetings.json";
import trPeople from "../../messages/phrases/tr/people.json";
import trPlatform from "../../messages/phrases/tr/platform.json";
import trPrivacy from "../../messages/phrases/tr/privacy.json";
import trRooms from "../../messages/phrases/tr/rooms.json";
import trSettings from "../../messages/phrases/tr/settings.json";
import trStudio from "../../messages/phrases/tr/studio.json";
import trTasks from "../../messages/phrases/tr/tasks.json";
import trWork from "../../messages/phrases/tr/work.json";
import trAutomations from "../../messages/phrases/tr/automations.json";
import trChannels from "../../messages/phrases/tr/channels.json";
import trData from "../../messages/phrases/tr/data.json";
import trConnectors from "../../messages/phrases/tr/connectors.json";
import trCrew from "../../messages/phrases/tr/crew.json";
import trAcademy from "../../messages/phrases/tr/academy.json";
import trVoice from "../../messages/phrases/tr/voice.json";

type Map = Record<string, string>;
const merge = (...parts: Map[]): Map => Object.assign({}, ...parts);

export const PHRASES: Record<Exclude<V2Locale, "en">, Map> = {
  ar: merge(arAi, arCommon, arCreate, arPrivacy, arSettings, arWork, arRooms, arTasks, arPeople, arStudio, arAiadmin, arPlatform, arDocs, arMeetings, arAutomations, arChannels, arData, arConnectors, arCrew, arAcademy, arVoice),
  tr: merge(trAi, trCommon, trCreate, trPrivacy, trSettings, trWork, trRooms, trTasks, trPeople, trStudio, trAiadmin, trPlatform, trDocs, trMeetings, trAutomations, trChannels, trData, trConnectors, trCrew, trAcademy, trVoice),
  fr: merge(frAi, frCommon, frCreate, frPrivacy, frSettings, frWork, frRooms, frTasks, frPeople, frStudio, frAiadmin, frPlatform, frDocs, frMeetings, frAutomations, frChannels, frData, frConnectors, frCrew, frAcademy, frVoice),
  pt: merge(ptAi, ptCommon, ptCreate, ptPrivacy, ptSettings, ptWork, ptRooms, ptTasks, ptPeople, ptStudio, ptAiadmin, ptPlatform, ptDocs, ptMeetings, ptAutomations, ptChannels, ptData, ptConnectors, ptCrew, ptAcademy, ptVoice),
};
/** Kept for older imports and tests. */
export const AR_PHRASES = PHRASES.ar;

type Vars = Record<string, string | number>;

function fill(text: string, vars?: Vars): string {
  if (!vars) return text;
  return text.replace(/\{(\w+)\}/g, (match, name: string) => (name in vars ? String(vars[name]) : match));
}

const CONTEXT = /^[a-z][a-z ]*\|/;

export function translate(locale: V2Locale, text: string, vars?: Vars): string {
  const english = text.replace(CONTEXT, "");
  const map = locale === "en" ? null : PHRASES[locale];
  return fill(map ? (map[text] ?? map[english] ?? english) : english, vars);
}

export function useTr() {
  const locale = useLocale();
  return useCallback((text: string, vars?: Vars) => translate(locale, text, vars), [locale]);
}
