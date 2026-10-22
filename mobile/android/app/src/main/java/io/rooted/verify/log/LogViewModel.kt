package io.rooted.verify.log

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import io.rooted.verify.api.LogResponse
import io.rooted.verify.api.RootedApiException
import io.rooted.verify.api.RootedClient
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

sealed interface LogUiState {
    data object Loading : LogUiState
    data class Loaded(val log: LogResponse) : LogUiState
    data class Error(val message: String) : LogUiState
}

class LogViewModel(
    private val client: RootedClient = RootedClient(),
) : ViewModel() {

    private val _state = MutableStateFlow<LogUiState>(LogUiState.Loading)
    val state: StateFlow<LogUiState> = _state.asStateFlow()

    private var requested = false

    fun loadIfNeeded() {
        if (!requested) refresh()
    }

    fun refresh() {
        requested = true
        _state.value = LogUiState.Loading
        viewModelScope.launch {
            try {
                _state.value = LogUiState.Loaded(client.log())
            } catch (e: RootedApiException) {
                _state.value = LogUiState.Error(e.message ?: "Request failed.")
            } catch (e: Exception) {
                _state.value = LogUiState.Error(
                    "Network error: ${e.message ?: e.javaClass.simpleName}. " +
                        "The live API was unreachable."
                )
            }
        }
    }
}
