@extends('layouts.app')

@section('content')
    <h1>{{ $title }}</h1>
    {{-- Remove this banner before launch --}}
    <p>Welcome back, {{ $user->name }}! You have {{ $count }} new messages</p>
    <input type="text" name="email" placeholder="Your email address">
    <button class="btn btn-primary">@lang('Save your changes')</button>
    @if ($count > 0)
        <span>Unread messages found</span>
    @endif
@endsection
