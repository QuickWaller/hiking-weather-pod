#include "NijntjeSpriteRegistry.h"
#include "sprites/NijntjeWalking.h"
#include "sprites/NijntjeWalkingHot.h"
#include "sprites/NijntjeWalkingCold.h"
#include "sprites/NijntjeWalkingFoggy.h"
#include "sprites/NijntjeWalkingNight.h"
#include "sprites/NijntjeClimbing.h"
#include "sprites/NijntjeClimbingHot.h"
#include "sprites/NijntjeClimbingCold.h"
#include "sprites/NijntjeClimbingFoggy.h"
#include "sprites/NijntjeResting.h"
#include "sprites/NijntjeRestingHot.h"
#include "sprites/NijntjeRestingCold.h"
#include "sprites/NijntjeRestingFoggy.h"
#include "sprites/NijntjeSleepyEvening.h"
#include "sprites/NijntjeSleepingTent.h"
#include "sprites/NijntjeWorried.h"
#include "sprites/NijntjeConnected.h"

NijntjeSprite lookupSprite(NijntjeState state, NijntjeModifier modifier) {
    switch (state) {
        case NijntjeState::Walking:
            switch (modifier) {
                case NijntjeModifier::Hot:   return {NijntjeWalkingHot,   NijntjeWalkingHot_WIDTH,   NijntjeWalkingHot_HEIGHT};
                case NijntjeModifier::Cold:  return {NijntjeWalkingCold,  NijntjeWalkingCold_WIDTH,  NijntjeWalkingCold_HEIGHT};
                case NijntjeModifier::Foggy: return {NijntjeWalkingFoggy, NijntjeWalkingFoggy_WIDTH, NijntjeWalkingFoggy_HEIGHT};
                default:                     return {NijntjeWalking,      NijntjeWalking_WIDTH,      NijntjeWalking_HEIGHT};
            }
        case NijntjeState::Climbing:
            switch (modifier) {
                case NijntjeModifier::Hot:   return {NijntjeClimbingHot,   NijntjeClimbingHot_WIDTH,   NijntjeClimbingHot_HEIGHT};
                case NijntjeModifier::Cold:  return {NijntjeClimbingCold,  NijntjeClimbingCold_WIDTH,  NijntjeClimbingCold_HEIGHT};
                case NijntjeModifier::Foggy: return {NijntjeClimbingFoggy, NijntjeClimbingFoggy_WIDTH, NijntjeClimbingFoggy_HEIGHT};
                default:                     return {NijntjeClimbing,      NijntjeClimbing_WIDTH,      NijntjeClimbing_HEIGHT};
            }
        case NijntjeState::Resting:
            switch (modifier) {
                case NijntjeModifier::Hot:   return {NijntjeRestingHot,   NijntjeRestingHot_WIDTH,   NijntjeRestingHot_HEIGHT};
                case NijntjeModifier::Cold:  return {NijntjeRestingCold,  NijntjeRestingCold_WIDTH,  NijntjeRestingCold_HEIGHT};
                case NijntjeModifier::Foggy: return {NijntjeRestingFoggy, NijntjeRestingFoggy_WIDTH, NijntjeRestingFoggy_HEIGHT};
                default:                     return {NijntjeResting,      NijntjeResting_WIDTH,      NijntjeResting_HEIGHT};
            }
        case NijntjeState::WalkingNight:  return {NijntjeWalkingNight,  NijntjeWalkingNight_WIDTH,  NijntjeWalkingNight_HEIGHT};
        case NijntjeState::SleepyEvening: return {NijntjeSleepyEvening, NijntjeSleepyEvening_WIDTH, NijntjeSleepyEvening_HEIGHT};
        case NijntjeState::SleepingTent:  return {NijntjeSleepingTent,  NijntjeSleepingTent_WIDTH,  NijntjeSleepingTent_HEIGHT};
        case NijntjeState::Worried:       return {NijntjeWorried,       NijntjeWorried_WIDTH,       NijntjeWorried_HEIGHT};
        case NijntjeState::Connected:     return {NijntjeConnected,     NijntjeConnected_WIDTH,     NijntjeConnected_HEIGHT};
        default:                          return {NijntjeWalking,       NijntjeWalking_WIDTH,       NijntjeWalking_HEIGHT};
    }
}
