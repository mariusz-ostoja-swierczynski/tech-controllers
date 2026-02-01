// Tech Thermostat Card - Complete implementation from Home Assistant
// Based on ha-state-control-climate-temperature with full temperature control logic
// Enhanced with custom timer functionality for Tech Controllers

import { LitElement, html, css } from 'https://unpkg.com/lit@3/index.js?module';

// Constants
const UNIT_F = "°F";
const UNAVAILABLE = "unavailable";

// Helper functions
const clamp = (value, min, max) => Math.max(min, Math.min(value, max));

class TechThermostatCard extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      config: { type: Object },
      _duration: { type: Number },
      _showTimerDialog: { type: Boolean },
      _targetTemperature: { type: Number },
    };
  }

  setConfig(config) {
    if (!config.entity) {
      throw new Error("Entity is required");
    }
    const domain = config.entity.split(".")[0];
    if (!["climate", "water_heater"].includes(domain)) {
      throw new Error("Specify an entity from within the climate or water_heater domain");
    }
    this.config = config;
  }

  constructor() {
    super();
    this._duration = 60;
    this._showTimerDialog = false;
    this._targetTemperature = null;
  }

  get _stateObj() {
    return this.hass?.states[this.config?.entity];
  }

  willUpdate(changedProps) {
    super.willUpdate(changedProps);
    if (changedProps.has("_stateObj") || (this.hass && this._targetTemperature == null && this._stateObj)) {
      const stateObj = this._stateObj;
      if (stateObj) {
        this._targetTemperature = stateObj.attributes?.temperature;
      }
    }
  }

  get _step() {
    const stateObj = this._stateObj;
    if (!stateObj) return 0.5;
    return stateObj.attributes?.target_temp_step ||
      (this.hass?.config?.unit_system?.temperature === UNIT_F ? 1 : 0.5);
  }

  get _min() {
    return this._stateObj?.attributes?.min_temp;
  }

  get _max() {
    return this._stateObj?.attributes?.max_temp;
  }

  get _containerStyle() {
    const stateObj = this._stateObj;
    const hvacAction = stateObj?.attributes?.hvac_action;
    const stateColor = "--state-color: var(--state-climate-heat-color, var(--state-climate-active-color, var(--state-active-color)));";

    // Only apply action color when actively heating
    if (hvacAction === "heating") {
      return `--action-color: var(--state-climate-heat-color, var(--state-climate-active-color, var(--state-active-color))); ${stateColor}`;
    }

    // For idle/off states, don't set action color (CSS fallbacks will handle it)
    return stateColor;
  }

  getCardSize() {
    return 7;
  }

  getGridOptions() {
    const columns = 12;
    let min_rows = 5;
    const min_columns = 6;
    if (this.config?.features?.length) {
      const featureHeight = Math.ceil((this.config.features.length * 2) / 3);
      rows += featureHeight;
      min_rows += featureHeight;
    }
    return { columns, min_rows, min_columns, };
  }

  // _handleMoreInfo = () => {
  //   this.dispatchEvent(new CustomEvent('hass-more-info', {
  //     detail: { entityId: this.config.entity },
  //     bubbles: true,
  //     composed: true
  //   }));
  // }

  _handleDurationChange = (e) => {
    const value = parseInt(e.target.value, 10);
    if (!isNaN(value) && value > 0) {
      this._duration = value;
      this.requestUpdate();
    }
  }

  _handleQuickDuration = (minutes) => {
    this._duration = minutes;
    this.requestUpdate();
  }

  _toggleTimerDialog = () => {
    this._showTimerDialog = !this._showTimerDialog;
  }

  _formatDuration(minutes) {
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    const hourLabel = this.hass.localize("ui.common.duration.hours_short") || "h";
    const minLabel = this.hass.localize("ui.common.duration.minutes_short") || "m";

    if (hours > 0 && mins > 0) {
      return `${hours}${hourLabel} ${mins}${minLabel}`;
    } else if (hours > 0) {
      return `${hours}${hourLabel}`;
    }
    return `${mins}${minLabel}`;
  }

  _handleApplyWithTimer = () => {
    if (!this.hass) return;
    this.hass.callService("tech", "set_temperature_with_duration", {
      entity_id: this.config.entity,
      temperature: this._targetTemperature,
      duration_minutes: this._duration,
    });
    this._showTimerDialog = false;
    this.requestUpdate();
  }

  _handleSetTemp = () => {
    if (!this.hass) return;
    this.hass.callService("climate", "set_temperature", {
      entity_id: this.config.entity,
      temperature: this._targetTemperature,
    });
  }

  // Temperature control methods from HA

  _valueChanged = (ev) => {
    const value = ev.detail?.value;
    if (isNaN(value)) return;
    this._targetTemperature = value;
  }

  _valueChanging = (ev) => {
    const value = ev.detail?.value;
    if (isNaN(value)) return;
    this._targetTemperature = value;
  }

  _handleButton = (ev) => {
    const step = parseFloat(ev.currentTarget.getAttribute('data-step'));
    let temp = this._targetTemperature ?? this._min;
    temp += step;
    temp = clamp(temp, this._min, this._max);
    this._targetTemperature = temp;
  }

  _renderLabel() {
    const stateObj = this._stateObj;
    if (stateObj?.state === UNAVAILABLE) {
      return html`<p class="label disabled">${this.hass.formatEntityState(stateObj)}</p>`;
    }
    const action = stateObj?.attributes?.hvac_action;
    return html`
      <p class="label">
        ${action && action !== "off"
        ? this.hass.formatEntityAttributeValue(stateObj, "hvac_action")
        : this.hass.formatEntityState(stateObj)}
      </p>
    `;
  }

  _renderPrimary() {
    const stateObj = this._stateObj;
    const currentTemperature = stateObj?.attributes?.current_temperature;
    const unit = this.hass?.config?.unit_system?.temperature || "°C";

    if (currentTemperature != null) {
      return html`
        <ha-big-number
          .value=${currentTemperature}
          .unit=${unit}
          .hass=${this.hass}
          .formatOptions=${{ maximumFractionDigits: 1 }}
        ></ha-big-number>
      `;
    }
    return html`<p class="primary-state">${stateObj?.state || ""}</p>`;
  }

  _renderSecondary() {
    if (!this._stateObj) return html`<p class="label"></p>`;
    const targetTemperature = this._targetTemperature;

    if (targetTemperature != null) {
      return html`
        <p class="label">
          <ha-icon icon="mdi:thermometer"></ha-icon>
          ${this.hass.formatEntityAttributeValue(this._stateObj, "temperature", targetTemperature)}
        </p>
      `;
    }
    return html`<p class="label"></p>`;
  }

  _handleApply = () => {
    if (this._showTimerDialog && this._duration > 0) {
      this._handleApplyWithTimer();
    } else {
      this._handleSetTemp();
    }
  }

  _renderApplyButtons() {
    const stateObj = this._stateObj;
    const hasChanges = this._targetTemperature !== stateObj?.attributes?.temperature;
    const permanentLabel = "∞";
    return html`
      <div class="apply-row ${hasChanges ? '' : 'disabled'}">
        <ha-button
          variant="neutral"
          appearance="outlined"
          class="timer-toggle ${this._showTimerDialog ? 'active' : ''}"
          @click=${this._toggleTimerDialog}
          ?disabled=${!hasChanges}
        >
          ${this._showTimerDialog ? html`<ha-icon slot="start" icon="mdi:clock-outline"></ha-icon>` : null}
          ${this._showTimerDialog ? this._formatDuration(this._duration) : permanentLabel}
        </ha-button>
        <ha-button
          variant="brand"
          appearance="filled"
          class="apply-btn"
          @click=${this._handleApply}
          ?disabled=${!hasChanges}>
          <ha-icon icon="mdi:check"></ha-icon>
        </ha-button>
      </div>
    `;
  }

  _renderInfo() {
    return html`
      <div class="info">
        ${this._renderLabel()}
        ${this._renderPrimary()}
        ${this._renderSecondary()}
        ${this._renderApplyButtons()}
      </div>
    `;
  }

  _renderTemperatureButtons() {
    return html`
      <div class="buttons">
        <ha-outlined-icon-button data-step="${-this._step}" @click=${this._handleButton} title="Decrease">
          <ha-icon icon="mdi:minus"></ha-icon>
        </ha-outlined-icon-button>
        <ha-outlined-icon-button data-step="${this._step}" @click=${this._handleButton} title="Increase">
          <ha-icon icon="mdi:plus"></ha-icon>
        </ha-outlined-icon-button>
      </div>
    `;
  }

  static get styles() {
    return css`
      :host {
        display: block;
        height: 100%;
      }
      ha-card {
        position: relative;
        width: 100%;
        padding: 0;
        display: flex;
        flex-direction: column;
        align-items: center;
      }

      .container {
        display: flex;
        align-items: center;
        justify-content: center;
        position: relative;
        overflow: hidden;
        max-width: 100%;
        box-sizing: border-box;
        padding: 8px;
      }

      ha-control-circular-slider {
        --control-circular-slider-low-color: var(--low-color, var(--disabled-color));
        --control-circular-slider-high-color: var(--high-color, var(--disabled-color));
        width: 100%;
        --control-circular-slider-color: var(--state-color, var(--disabled-color));
      }

      ha-control-circular-slider::after {
        display: block;
        content: "";
        position: absolute;
        top: -10%;
        left: -10%;
        right: -10%;
        bottom: -10%;
        background: radial-gradient(50% 50% at 50% 50%, var(--action-color, transparent) 0%, transparent 100%);
        opacity: 0.15;
        pointer-events: none;
      }

      .title {
        width: 100%;
        line-height: var(--ha-line-height-expanded, 1.5);
        padding: 8px 30px;
        margin: 0;
        text-align: center;
        box-sizing: border-box;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        flex: none;
      }

      .info {
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        pointer-events: none;
        font-size: var(--ha-font-size-l);
        line-height: var(--ha-line-height-normal, 1.5);
        letter-spacing: .1px;
        gap: var(--ha-space-2, 8px);
        --mdc-icon-size: 16px;
      }

      .label {
        margin: 0;
        font-size: 14px;
        width: 60%;
        font-weight: var(--ha-font-weight-medium);
        text-align: center;
        color: var(--action-color, inherit);
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
        line-height: var(--ha-line-height-normal);
        min-height: 1.5em;
        white-space: nowrap;
      }

      .apply-row {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-top: 8px;
        pointer-events: auto;
        transition: opacity 200ms;
      }

      .apply-row.disabled {
        opacity: 0.4;
        pointer-events: none;
      }

      .timer-toggle {
        min-width: 105px;
      }
      
      .buttons {
        position: absolute;
        bottom: 10px;
        left: 0;
        right: 0;
        margin: 0 auto;
        gap: 24px;
        display: flex;
        flex-direction: row;
        align-items: center;
        justify-content: center;
      }
      
      .more-info {
        position: absolute;
        cursor: pointer;
        top: 0;
        right: 0;
        inset-inline-end: 0px;
        inset-inline-start: initial;
        border-radius: var(--ha-border-radius-pill, 50px);
        color: var(--secondary-text-color);
        background: none;
        border: none;
        padding: 8px;
        font-size: 20px;
        direction: var(--direction, ltr);
      }

      .more-info:hover {
        background: var(--primary-color);
        color: white;
      }

      .timer-section {
        width: 100%;
        box-sizing: border-box;
        display: flex;
        flex-direction: column;
        gap: 24px;
        padding: 0 12px 12px 12px;
      }

      .timer-section ha-slider {
        width: 100%;
      }

      .timer-quick-buttons {
        display: flex;
        gap: 8px;
      }

      .timer-quick-buttons ha-button {
        flex: 1;
      }

      .duration-label {
        min-width: 60px;
        text-align: right;
        font-size: 14px;
      }
    `;
  }

  render() {
    if (!this.hass || !this.config?.entity) {
      return html`<ha-card><div style="padding: 16px;">Entity not configured</div></ha-card>`;
    }

    if (!this._stateObj) {
      return html`
        <ha-card>
          <div style="padding: 16px; text-align: center; color: var(--error-color);">
            Entity not found: ${this.config.entity}
          </div>
        </ha-card>
      `;
    }

    const stateObj = this._stateObj;
    const name = stateObj.attributes?.friendly_name || this.config.entity;

    return html`
      <ha-card>
        <p class="title">${name}</p>
        <div class="container" style="${this._containerStyle}">
          <ha-control-circular-slider
            prevent-interaction-on-scroll
            .value=${this._targetTemperature}
            .min=${this._min}
            .max=${this._max}
            .step=${this._step}
            .current=${stateObj.attributes?.current_temperature}
            @value-changed=${this._valueChanged}
            @value-changing=${this._valueChanging}
          ></ha-control-circular-slider>
          ${this._renderInfo()}
          ${this._renderTemperatureButtons()}
        </div>

        ${this._showTimerDialog ? html`
          <div class="timer-section">

              <div class="timer-quick-buttons">
                <ha-button variant="neutral" class="${this._duration === 60 ? 'active' : ''}" @click=${() => this._handleQuickDuration(60)}>1h</ha-button>
                <ha-button variant="neutral" class="${this._duration === 120 ? 'active' : ''}" @click=${() => this._handleQuickDuration(120)}>2h</ha-button>
                <ha-button variant="neutral" class="${this._duration === 240 ? 'active' : ''}" @click=${() => this._handleQuickDuration(240)}>4h</ha-button>
                <ha-button variant="neutral" class="${this._duration === 480 ? 'active' : ''}" @click=${() => this._handleQuickDuration(480)}>8h</ha-button>
              </div>
                <ha-slider
                  labeled
                  .value=${this._duration}
                  .min=${1}
                  .max=${1440}
                  .step=${5}
                  .valueFormatter=${(value) => this._formatDuration(value)}
                  @input=${this._handleDurationChange}
                ></ha-slider>

          </div>
        ` : ''}
      </ha-card>
    `;
  }

  static getConfigElement() {
    return document.createElement("tech-thermostat-card-editor");
  }

  static getStubConfig(hass) {
    // Find first climate entity for preview
    const climateEntity = Object.keys(hass.states).find(
      (entityId) => entityId.startsWith("climate.")
    );
    return { entity: climateEntity || "" };
  }
}

// Visual Editor for the card
class TechThermostatCardEditor extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      _config: { type: Object },
    };
  }

  setConfig(config) {
    this._config = { ...config };
  }

  get _schema() {
    return [
      {
        name: "entity",
        required: true,
        selector: {
          entity: {
            domain: "climate",
          },
        },
      },
    ];
  }

  _valueChanged(ev) {
    const config = ev.detail.value;
    this.dispatchEvent(new CustomEvent("config-changed", {
      detail: { config },
      bubbles: true,
      composed: true,
    }));
  }

  render() {
    if (!this.hass || !this._config) {
      return html``;
    }

    return html`
      <ha-form
        .hass=${this.hass}
        .data=${this._config}
        .schema=${this._schema}
        .computeLabel=${(schema) => schema.name === "entity" ? "Entity" : schema.name}
        @value-changed=${this._valueChanged}
      ></ha-form>
    `;
  }

}

customElements.define("tech-thermostat-card-editor", TechThermostatCardEditor);
customElements.define("tech-thermostat-card", TechThermostatCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "tech-thermostat-card",
  name: "Tech Thermostat",
  description: "Thermostat card with timer functionality for Tech Controllers",
  preview: true,
  documentationURL: "https://github.com/mariusz-ostoja-swierczynski/tech-controllers",
});
