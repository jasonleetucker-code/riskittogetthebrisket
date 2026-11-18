/**
 * Which row of the account's device list is THIS browser.
 *
 * The phone-alerts page used to call "this device" the first live device on
 * the account whenever this browser held any subscription, so with two phones
 * the test went to the wrong one and "linked" described another device.  The
 * device list carries no endpoint, so the only honest identity is the
 * `deviceId` the server returned when THIS browser's own subscription was
 * registered (`POST /notify/devices` → {deviceId}).
 */

/** The `deviceId` the server returned for this browser's subscription, or null. */
export function thisDeviceId(registration) {
  const id = registration?.deviceId;
  return Number.isInteger(id) ? id : null;
}

/**
 * This browser's row, matched by its own id — never "the first live device".
 * No subscription here, or no id from the server, means this device is not
 * identified and nothing else stands in for it.
 */
export function findThisDevice(devices, hereDeviceId, hereSub) {
  if (!hereSub || hereDeviceId == null || !Array.isArray(devices)) return null;
  return devices.find((d) => d?.id === hereDeviceId) || null;
}
